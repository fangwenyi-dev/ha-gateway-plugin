#!/usr/bin/env python3
"""
慧尖 LoRa 网关 mDNS 广播服务

使用 zeroconf 库直接通过 UDP multicast 广播 mDNS 服务和主机名，
不依赖 D-Bus / avahi-daemon，避免与 HAOS 宿主 avahi-daemon 端口冲突。

注册内容：
  1. _mqtt._tcp 服务（LoRa 网关服务发现）
  2. huijian.local 主机名 A 记录（LoRa 网关 hostname 解析）
"""

import socket
import sys
import time

try:
    from zeroconf import ServiceInfo, Zeroconf
    # 尝试导入 IPVersion（不同版本 API 可能不同）
    try:
        from zeroconf import IPVersion
    except ImportError:
        IPVersion = None
except ImportError:
    print("[mDNS] zeroconf 库未安装，mDNS 不可用", file=sys.stderr)
    sys.exit(1)


def get_local_ip():
    """获取本机 IP（host_network 模式下就是 HA 主机 IP）"""
    # 方式 1: 连接外部地址获取本机出口 IP（最可靠）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # 方式 2: hostname -I 等效方式
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # 方式 3: 遍历所有网络接口
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and not ip.startswith("::"):
                return ip
    except Exception:
        pass

    return None


def main():
    mqtt_port = int(sys.argv[1]) if len(sys.argv) > 1 else 2022

    local_ip = get_local_ip()
    if not local_ip:
        # v1.6.3：绝不广播 127.0.0.1——旧实现在 IP 探测失败时把回环地址
        # 宣告为 huijian.local，LoRa 网关解析后对着自己发连接，永远失败
        # 且毫无排障线索。退出非零，交由 run.sh 看门狗 10 秒后重试。
        print("[mDNS] 无法确定本机 IP（网络未就绪？），退出等待看门狗重试", file=sys.stderr)
        sys.exit(1)

    print(f"[mDNS] 本机 IP: {local_ip}")

    # 创建 Zeroconf 实例
    # 不显式指定 ip_version，使用默认值（自动选择），避免不同版本 API 差异
    try:
        zeroconf = Zeroconf()
    except Exception as e:
        print(f"[mDNS] Zeroconf 初始化失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 注册 _mqtt._tcp 服务
    # zeroconf 0.132.0 要求 type_ 和 name 都以 .local. 结尾
    service_info = ServiceInfo(
        type_="_mqtt._tcp.local.",
        name="huijian-mqtt._mqtt._tcp.local.",
        addresses=[socket.inet_aton(local_ip)],
        port=mqtt_port,
        properties={},
        server="huijian.local.",
    )

    # 注册 huijian.local 主机名
    # zeroconf 通过 ServiceInfo 的 server 字段自动广播 A 记录
    # 同时也注册一个主机名服务

    try:
        zeroconf.register_service(service_info)
        print(f"[mDNS] _mqtt._tcp 服务已注册: huijian-mqtt._mqtt._tcp.local. @ {local_ip}:{mqtt_port}")
        print(f"[mDNS] huijian.local → {local_ip}")
        print(f"[mDNS] mDNS 广播中，LoRa 网关可通过 huijian.local:{mqtt_port} 连接")

        # 保持运行，mDNS 广播持续在线。
        # v1.6.3：每 30 秒复查本机 IP——DHCP 续租/换网后旧地址仍被广播，
        # 网关会连到失效 IP；IP 变化时注销并按新地址重注册。
        while True:
            time.sleep(30)
            current = get_local_ip()
            if current and current != local_ip:
                print(f"[mDNS] 本机 IP 变化: {local_ip} → {current}，重新注册")
                try:
                    zeroconf.unregister_service(service_info)
                except Exception:
                    pass
                service_info = ServiceInfo(
                    type_="_mqtt._tcp.local.",
                    name="huijian-mqtt._mqtt._tcp.local.",
                    addresses=[socket.inet_aton(current)],
                    port=mqtt_port,
                    properties={},
                    server="huijian.local.",
                )
                zeroconf.register_service(service_info)
                local_ip = current
                print(f"[mDNS] huijian.local → {local_ip}（已更新）")

    except KeyboardInterrupt:
        pass
    except Exception as e:
        # v1.6.3：注册/重注册失败退出非零，让看门狗接管重试
        # （旧实现吞异常后正常退出 0，广播静默消失且无人重启）
        print(f"[mDNS] 服务注册失败: {e}", file=sys.stderr)
        try:
            zeroconf.unregister_service(service_info)
            zeroconf.close()
        except Exception:
            pass
        sys.exit(2)
    finally:
        if sys.exc_info()[0] is None or isinstance(sys.exc_info()[1], KeyboardInterrupt):
            try:
                zeroconf.unregister_service(service_info)
                zeroconf.close()
            except Exception:
                pass
        print("[mDNS] mDNS 服务已注销")


if __name__ == "__main__":
    main()
