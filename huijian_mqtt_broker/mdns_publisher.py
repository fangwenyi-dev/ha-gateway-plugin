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
        print("[mDNS] 无法确定本机 IP，mDNS 广播可能不完整", file=sys.stderr)
        local_ip = "127.0.0.1"

    print(f"[mDNS] 本机 IP: {local_ip}")

    # 创建 Zeroconf 实例
    # 不显式指定 ip_version，使用默认值（自动选择），避免不同版本 API 差异
    try:
        zeroconf = Zeroconf()
    except Exception as e:
        print(f"[mDNS] Zeroconf 初始化失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 注册 _mqtt._tcp 服务
    service_info = ServiceInfo(
        type_="_mqtt._tcp.",
        name="huijian-mqtt._mqtt._tcp.",
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
        print(f"[mDNS] _mqtt._tcp 服务已注册: huijian-mqtt._mqtt._tcp. @ {local_ip}:{mqtt_port}")
        print(f"[mDNS] huijian.local → {local_ip}")
        print(f"[mDNS] mDNS 广播中，LoRa 网关可通过 huijian.local:{mqtt_port} 连接")

        # 保持运行，mDNS 广播持续在线
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[mDNS] 服务注册失败: {e}", file=sys.stderr)
    finally:
        zeroconf.unregister_service(service_info)
        zeroconf.close()
        print("[mDNS] mDNS 服务已注销")


if __name__ == "__main__":
    main()
