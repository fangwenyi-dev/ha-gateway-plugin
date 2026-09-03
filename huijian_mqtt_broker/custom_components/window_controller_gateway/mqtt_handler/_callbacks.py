"""_CallbacksMixin —— 状态回调注册/通知（weakref.WeakMethod 契约定案，勿改）

v1.6.25 拆包：代码自 mqtt_handler.py 单文件**逐字原样搬移**，禁止在此顺手优化；方法经
组合类 WindowControllerMQTTHandler 解析（单类形态与拆分前一致）。
"""
import logging
import weakref
from typing import Dict, Any, Callable, Union

# logger 名钉死为拆分前模块 __name__ 值——日志输出零差异（回归要求）
_LOGGER = logging.getLogger("custom_components.window_controller_gateway.mqtt_handler")


class _CallbacksMixin:
    def add_status_callback(self, *args: Union[str, Callable[[Union[str, Dict[str, Any]], Any], None]]):
        """添加状态更新回调
        
        支持两种调用方式：
        1. add_status_callback(device_sn, callback) - 为特定设备添加回调
        2. add_status_callback(callback) - 为网关添加回调
        
        Args:
            *args: 可变参数，
                - 方式1: (device_sn: str, callback: Callable)
                - 方式2: (callback: Callable)
        """
        def _get_weak_ref(callback):
            """获取回调的弱引用"""
            if hasattr(callback, '__self__') and hasattr(callback, '__func__'):
                # 实例方法
                return weakref.WeakMethod(callback)
            else:
                # 普通函数
                return weakref.ref(callback)
        
        if len(args) == 2:
            # 为特定设备添加回调
            device_sn, callback = args
            if device_sn not in self._status_callbacks:
                self._status_callbacks[device_sn] = []
            
            # 使用弱引用存储回调，避免内存泄漏
            weak_callback = _get_weak_ref(callback)
            # 检查是否已经存在相同的回调
            callback_exists = False
            for ref in self._status_callbacks[device_sn]:
                if ref() == callback:
                    callback_exists = True
                    break
            
            if not callback_exists:
                self._status_callbacks[device_sn].append(weak_callback)
                _LOGGER.debug("为设备 %s 添加状态更新回调", device_sn)
        elif len(args) == 1:
            # 为网关添加回调（向后兼容）
            callback = args[0]
            # 使用特殊键 "gateway" 存储网关回调
            if "gateway" not in self._status_callbacks:
                self._status_callbacks["gateway"] = []
            
            # 使用弱引用存储回调，避免内存泄漏
            weak_callback = _get_weak_ref(callback)
            # 检查是否已经存在相同的回调
            callback_exists = False
            for ref in self._status_callbacks["gateway"]:
                if ref() == callback:
                    callback_exists = True
                    break
            
            if not callback_exists:
                self._status_callbacks["gateway"].append(weak_callback)
                _LOGGER.debug("为网关添加状态更新回调")

    def remove_status_callback(self, *args: Union[str, Callable[[Union[str, Dict[str, Any]], Any], None]]):
        """移除状态更新回调
        
        支持两种调用方式：
        1. remove_status_callback(device_sn, callback) - 移除特定设备的回调
        2. remove_status_callback(callback) - 移除网关的回调
        
        Args:
            *args: 可变参数，
                - 方式1: (device_sn: str, callback: Callable)
                - 方式2: (callback: Callable)
        """
        if len(args) == 2:
            # 移除特定设备的回调
            device_sn, callback = args
            if device_sn in self._status_callbacks:
                # 找到并移除对应的弱引用
                refs_to_remove = []
                for ref in self._status_callbacks[device_sn]:
                    if ref() == callback:
                        refs_to_remove.append(ref)
                
                for ref in refs_to_remove:
                    self._status_callbacks[device_sn].remove(ref)
                    _LOGGER.debug("从设备 %s 移除状态更新回调", device_sn)
                
                # 清理无效的弱引用
                valid_refs = []
                for ref in self._status_callbacks[device_sn]:
                    if ref() is not None:
                        valid_refs.append(ref)
                
                if valid_refs:
                    self._status_callbacks[device_sn] = valid_refs
                else:
                    # 如果设备没有回调了，清理设备条目
                    del self._status_callbacks[device_sn]
                    _LOGGER.debug("清理设备 %s 的回调条目", device_sn)
        elif len(args) == 1:
            # 移除网关的回调（向后兼容）
            callback = args[0]
            if "gateway" in self._status_callbacks:
                # 找到并移除对应的弱引用
                refs_to_remove = []
                for ref in self._status_callbacks["gateway"]:
                    if ref() == callback:
                        refs_to_remove.append(ref)
                
                for ref in refs_to_remove:
                    self._status_callbacks["gateway"].remove(ref)
                    _LOGGER.debug("从网关移除状态更新回调")
                
                # 清理无效的弱引用
                valid_refs = []
                for ref in self._status_callbacks["gateway"]:
                    if ref() is not None:
                        valid_refs.append(ref)
                
                if valid_refs:
                    self._status_callbacks["gateway"] = valid_refs
                else:
                    # 如果网关没有回调了，清理网关条目
                    del self._status_callbacks["gateway"]
                    _LOGGER.debug("清理网关的回调条目")

    def _notify_status_change(self):
        """通知状态变化 - 确保在事件循环线程中执行回调"""
        # 此方法现在用于网关状态变化通知
        # 设备状态变化通知使用 _notify_device_status_change
        
        # 通知网关状态回调
        if "gateway" in self._status_callbacks:
            gateway_callbacks = self._status_callbacks["gateway"]
            valid_callbacks = []
            
            for ref in gateway_callbacks:
                callback = ref()
                if callback is not None:
                    valid_callbacks.append(callback)
                
            # 清理无效的弱引用
            self._status_callbacks["gateway"] = [ref for ref in gateway_callbacks if ref() is not None]
            
            for callback in valid_callbacks:
                try:
                    # 使用hass.add_job确保在事件循环线程中执行回调
                    self.hass.add_job(callback)
                except Exception as e:
                    _LOGGER.error("调用网关状态回调失败: %s", e)

    def _notify_device_status_change(self, device_sn):
        """通知设备状态变化 - 确保在事件循环线程中执行回调"""
        if device_sn in self._status_callbacks:
            device_callbacks = self._status_callbacks[device_sn]
            valid_callbacks = []
            
            for ref in device_callbacks:
                callback = ref()
                if callback is not None:
                    valid_callbacks.append(callback)
            
            # 清理无效的弱引用
            self._status_callbacks[device_sn] = [ref for ref in device_callbacks if ref() is not None]
            
            for callback in valid_callbacks:
                try:
                    # 使用hass.add_job确保在事件循环线程中执行回调
                    self.hass.add_job(callback)
                    _LOGGER.debug("通知设备 %s 状态更新回调", device_sn)
                except Exception as e:
                    _LOGGER.error("调用设备状态回调失败: %s", e)
            
            # 如果设备没有回调了，清理设备条目
            if not self._status_callbacks[device_sn]:
                del self._status_callbacks[device_sn]
                _LOGGER.debug("清理设备 %s 的回调条目", device_sn)
