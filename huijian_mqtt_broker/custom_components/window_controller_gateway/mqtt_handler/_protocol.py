"""_ProtocolMixin —— 入站解析与分发：订阅回调（handle_gateway_response）、cmd id 归一、去重分发、ack 发送、批量任务

v1.6.25 拆包：代码自 mqtt_handler.py 单文件**逐字原样搬移**，禁止在此顺手优化；方法经
组合类 WindowControllerMQTTHandler 解析（单类形态与拆分前一致）。
"""
import logging
import json
import asyncio
import time
import re
from homeassistant.components import mqtt
from ..const import (
    DOMAIN,
    CONF_GATEWAY_SN,
    ATTR_DEVICE_SN,
    ATTR_DEVICE_NAME,
    ATTR_POSITION,
    ATTR_BATTERY,
    DEVICE_TYPE_WINDOW_OPENER,
    PROTOCOL_HEAD,
    TOPIC_GATEWAY_RSP,
)

# logger 名钉死为拆分前模块 __name__ 值——日志输出零差异（回归要求）
_LOGGER = logging.getLogger("custom_components.window_controller_gateway.mqtt_handler")


class _ProtocolMixin:
    @staticmethod
    def _norm_cmd_id(raw):
        """命令 id 归一（v1.6.19 第六轮审计 A-LOW4）：_bind_ops 的键恒为
        int(self.command_id)，但网关回包的 id 可能以 "42"/42.0 形态 echo
        （去重层的 f-string 会抹平类型差异放行，pop 的精确匹配却会 miss，
        退回已知有竞态的存在性推断分支）。bool 特判 False→0/True→1 是固件
        id 语义里不存在的形态，原样返回交给 miss 分支处理。"""
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float) and raw.is_integer():
            return int(raw)
        if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
            try:
                return int(raw.strip())
            except ValueError:
                return raw
        return raw

    async def _subscribe_topics(self):
        """订阅MQTT主题 - 根据协议要求简化为只订阅网关响应主题"""
        # 取消旧订阅（防止重连时累积重复订阅）
        if self._unsub_rsp:
            try:
                self._unsub_rsp()
            except Exception as e:
                _LOGGER.debug("取消旧MQTT订阅时出错: %s", e)
            self._unsub_rsp = None
        
        # 订阅网关响应和数据主题
        def handle_gateway_response(msg):
            """处理网关响应和数据消息"""
            # v1.6.19（第六轮审计 A-LOW7）：入站尺寸闸。mosquitto 默认
            # message_size_limit 不限，LAN 上任一可连 2022 的客户端 publish
            # 一条 50-100MB 的 rpt_rsp 会在事件循环线程 json.loads 卡死整个
            # HA（本回调与分发全在 loop 内）。WS 侧有 1024B 帧闸，MQTT 侧
            # 对称补齐：>64KB 一律拒收（协议合法帧远小于此，最大 002 全量
            # 设备列表也仅数 KB）。
            try:
                if len(msg.payload) > 64 * 1024:
                    _LOGGER.warning(
                        "收到超大 MQTT 报文（%d 字节），拒收处理", len(msg.payload)
                    )
                    return
            except Exception:  # noqa: BLE001 - payload 非常规类型交给下方既有流程
                pass
            try:
                payload = json.loads(msg.payload)
                _LOGGER.debug("收到网关消息: %s", payload)
                
                # 检查是否是标准协议格式（带head和ctype字段）
                if "head" in payload and "ctype" in payload:
                    # 标准协议格式处理
                    ctype = payload.get("ctype")
                    data = payload.get("data", {})
                    # v1.6.19（第六轮审计 A-HIGH1）：data 归一为 dict。显式
                    # `"data": null` 时 payload.get("data", {}) 返回 None（键
                    # 存在、值无效，默认值不生效），非 dict 的 data 会让
                    # _handle_ctype_001 在 ack 发布前抛 TypeError/AttributeError
                    # ——网关按未确认无限重发，形成毒消息重传环（与 v1.6.12
                    # 第五轮 #1 在 005 修掉的是同一类面，当时漏了 001）。
                    # 在分发单点归一，全部 ctype 处理器同受保护。
                    if not isinstance(data, dict):
                        _LOGGER.warning(
                            "消息 data 字段非对象（%s），已归一为空对象: ctype=%s",
                            type(data).__name__, ctype,
                        )
                        data = {}
                    
                    # 检查响应是否来自此网关
                    response_sn = payload.get("sn")
                    if not response_sn:
                        return

                    # P0 类型守卫：网关固件可能以 JSON 数字形式发送 SN（int/float），
                    # 统一转为字符串再比较；其他畸形类型（bool/dict/list 等）只丢弃
                    # 本消息并记录一行警告，绝不能因 AttributeError 崩溃导致整帧
                    # （含心跳）处理中断 → 网关被误判离线长达超时窗口。
                    if isinstance(response_sn, bool) or not isinstance(response_sn, (str, int, float)):
                        _LOGGER.warning("收到网关SN类型非法，忽略该消息: %r", response_sn)
                        return
                    if not isinstance(response_sn, str):
                        response_sn = str(response_sn)

                    # 消息去重检查 - 使用 ctype + id + sn 作为唯一标识
                    msg_key = f"{ctype}_{payload.get('id', 0)}_{response_sn}"
                    # v1.6.11（审计 #5）：去重时间轴换 monotonic——time.time()
                    # 遇 NTP 回跳会令剪枝条件（current_time - v < duration）
                    # 长期为真，旧条目滞留到时钟追平。该字典唯一喂入点在此，
                    # 与 _dispatch_with_dedup 的剪枝同一时基，整体切换安全；
                    # 网关超时判定（_check_gateway_timeout）本就独立用
                    # monotonic，互不掺混
                    current_time = time.monotonic()
                    
                    # 如果是来自其他网关的消息，触发网关发现
                    if response_sn.lower() != self.gateway_sn.lower():
                        # 防御校验：response_sn 来自 MQTT payload（攻击者可控），
                        # 必须满足 SN 格式（≥10 位字母数字），避免畸形 SN 进入发现/配置流程
                        if not isinstance(response_sn, str) or not re.match(r"^[a-zA-Z0-9]{10,}$", response_sn):
                            _LOGGER.warning("收到格式非法的网关SN，忽略: %r", response_sn)
                            return
                        try:
                            # 快速检查：如果该网关已在配置条目中，跳过发现触发
                            already_configured = False
                            for entry in self.hass.config_entries.async_entries(DOMAIN):
                                if entry.data.get(CONF_GATEWAY_SN, "").lower() == response_sn.lower():
                                    already_configured = True
                                    break
                            
                            if not already_configured:
                                from .discovery import async_discover_gateway
                                gateway_name = f"网关 {response_sn[-4:]}"
                                
                                # 检查是否处于替换模式
                                replace_mode = False
                                for flow in self.hass.config_entries.flow.async_progress():
                                    if flow["handler"] == DOMAIN and flow.get("context", {}).get("source") == "replace_gateway":
                                        replace_mode = True
                                        break
                                
                                # 触发网关发现，传入替换模式标志
                                self._schedule_async_task(
                                    async_discover_gateway(self.hass, response_sn, gateway_name, replace_mode, self.gateway_sn)
                                )
                        except Exception as e:
                            _LOGGER.error("触发未配置网关发现失败: %s", e)
                        return
                    
                    # 更新最后上报时间 - 只要收到网关消息就认为在线（单调时钟）
                    self.last_gateway_report_time = time.monotonic()
                    
                    # 只要收到网关消息就认为在线，更新connected状态
                    if not self.connected:
                        self.connected = True
                        self._notify_status_change()
                        _LOGGER.info("网关 %s 收到消息，标记为在线", self.gateway_sn)
                    
                    # 根据不同的消息类型调用相应的处理函数
                    ctype_handlers = {
                        "001": self._handle_ctype_001,
                        "002": self._handle_ctype_002,
                        "003": self._handle_ctype_003,
                        "004": self._handle_ctype_004,
                        "005": self._handle_ctype_005,
                        "006": self._handle_ctype_006,
                        "007": self._handle_ctype_007
                    }
                    
                    if ctype in ctype_handlers:
                        msg_id = payload.get("id", 0)
                        if msg_id in (0, None):
                            # 网关周期上报（002/005）的 id 可能恒为 0：
                            # 若按 ctype+id+sn 去重，5 秒窗口内的后续上报会被误杀，
                            # 导致设备状态/位置更新丢失。id 无效时直接调度
                            # （处理函数幂等，重复处理无害）。
                            self._schedule_async_task(
                                ctype_handlers[ctype](payload, ctype, data)
                            )
                        else:
                            self._schedule_async_task(
                                self._dispatch_with_dedup(
                                    ctype_handlers[ctype](payload, ctype, data),
                                    msg_key,
                                    current_time
                                )
                            )
                    else:
                        _LOGGER.warning("未知的消息类型: %s", ctype)
                    
                    return
                
                # 处理原有格式的响应（向后兼容）
                gateway_sn = payload.get("gateway_sn")
                if not gateway_sn:
                    return
                # P0 类型守卫：与标准协议格式的 sn 字段一致，畸形类型只丢弃本消息
                if isinstance(gateway_sn, bool) or not isinstance(gateway_sn, (str, int, float)):
                    _LOGGER.warning("收到网关SN类型非法，忽略该消息: %r", gateway_sn)
                    return
                if not isinstance(gateway_sn, str):
                    gateway_sn = str(gateway_sn)
                if gateway_sn.lower() != self.gateway_sn.lower():
                    return
                
                response_type = payload.get("type")
                
                if response_type == "device_discovery":
                    devices = payload.get("devices", [])
                    for device_info in devices:
                        device_sn = device_info.get(ATTR_DEVICE_SN)
                        device_name = device_info.get(ATTR_DEVICE_NAME, f"设备 {device_sn[-6:]}")
                        device_type = device_info.get("device_type", DEVICE_TYPE_WINDOW_OPENER)
                        
                        self._schedule_async_task(
                            self.device_manager.add_device(device_sn, device_name, device_type)
                        )
                        
                elif response_type == "device_status":
                    device_sn = payload.get(ATTR_DEVICE_SN)
                    if not device_sn:
                        return
                    
                    status = payload.get("status", "unknown")
                    attributes = {}
                    
                    if ATTR_POSITION in payload:
                        attributes[ATTR_POSITION] = payload[ATTR_POSITION]
                    if ATTR_BATTERY in payload:
                        attributes[ATTR_BATTERY] = payload[ATTR_BATTERY]
                    
                    self._schedule_async_task(
                        self.device_manager.update_device_status(device_sn, status, attributes)
                    )
                    
            except json.JSONDecodeError:
                _LOGGER.error("MQTT消息解析失败: %s", msg.payload)
            except KeyError as e:
                _LOGGER.error("MQTT消息缺少必要字段: %s", e)
            except ValueError as e:
                _LOGGER.error("MQTT消息数据格式错误: %s", e)
            except Exception as e:
                _LOGGER.error("处理网关消息时出错: %s", e)
        
        try:
            # 订阅网关响应主题
            self._unsub_rsp = await mqtt.async_subscribe(self.hass, self.TOPIC_GATEWAY_RSP, handle_gateway_response, 1)
            _LOGGER.debug("订阅网关消息主题: %s", self.TOPIC_GATEWAY_RSP)
        except ConnectionError as e:
            _LOGGER.error("MQTT连接失败: %s", e)
        except TimeoutError as e:
            _LOGGER.error("MQTT订阅超时: %s", e)
        except Exception as e:
            _LOGGER.error("订阅MQTT主题失败: %s", e)
            # 触发重连逻辑
            self._schedule_reconnect()

    async def _batch_process_tasks(self, tasks, task_type="处理"):
        """批处理异步任务
        
        Args:
            tasks: 要执行的异步任务列表
            task_type: 任务类型描述，用于日志
        """
        if not tasks:
            return
        
        batch_size = 10
        total_success = 0
        for i in range(0, len(tasks), batch_size):
            batch_tasks = tasks[i:i+batch_size]
            results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            total_success += success_count
            # v1.6.12（第五轮审计 #2）：子任务异常此前只被计数、内容整体丢弃
            # （毒数据引发静默丢更新时无从排查），逐条记警告
            for r in results:
                if isinstance(r, Exception):
                    _LOGGER.warning("批量%s子任务异常: %r", task_type, r)
            _LOGGER.info("批量%s完成，批次: %d，成功: %d，总数: %d", 
                       task_type, i//batch_size + 1, success_count, len(batch_tasks))
        _LOGGER.info("所有批次%s完成，总成功: %d，总总数: %d", task_type, total_success, len(tasks))

    async def _dispatch_with_dedup(self, handler_coro, msg_key: str, current_time: float):
        """带去重检查的异步任务分发"""
        async with self._msg_lock:
            self._processed_messages = {
                k: v for k, v in self._processed_messages.items()
                if current_time - v < self._message_dedup_duration
            }
            if msg_key in self._processed_messages:
                _LOGGER.debug("跳过重复消息: %s", msg_key)
                handler_coro.close()
                return
            self._processed_messages[msg_key] = current_time
        await handler_coro

    async def _send_ack(self, ctype: str, payload: dict):
        """发送确认响应到网关（用于网关主动发起的消息）

        网关主动发起的消息（001/002/005）需要 HA 回复 errcode:0 确认，
        否则网关会重复重发。
        HA 主动下发的命令（003/004/006/007）由网关回复，HA 不需要再回复。
        """
        response_payload = {
            "head": PROTOCOL_HEAD,
            "ctype": ctype,
            "id": payload.get("id", 0),
            "sn": self.gateway_sn,
            "data": {
                "errcode": 0
            }
        }
        await mqtt.async_publish(
            self.hass,
            self.TOPIC_GATEWAY_REQ,
            json.dumps(response_payload),
            1,
            False
        )
        _LOGGER.debug("已发送%s确认响应，id: %s", ctype, payload.get("id", 0))
