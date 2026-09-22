"""服务目录三方一致守卫（v1.7.32 全量审计：服务真值源漂移）。

三方各自维护同一份服务目录，彼此无对账：
- `services.yaml`（HA 开发者工具「服务」页的表单与说明）
- `strings.json` / `translations/zh-CN.json`（服务名与描述的本地化源）
- `services.py` 的实际注册集

实测缺陷（本守卫立前）：`unignore_gateway` 在 yaml 有、两语言 strings **零
条目**（HA 服务页裸显 key，用户无从知道它干什么——而它正是「误点忽略后
唯一自救出口」）；反向 `migrate_devices` 在两语言 strings 里有，而注册
代码已整段注释禁用、yaml 也无该项，属孤儿文案。

判定口径：
1. 双语键集合必须相等（任一侧漏键即红）；
2. `services.yaml` 每个服务必须在双语 strings 都有条目（yaml 是对用户的
   承诺面，缺文案即半成品）；
3. strings 里比 yaml 多出来的键必须恰好等于显式登记的「已禁用但有文案」
   白名单——加一个例外就必须改一次这个常量，防孤儿文案重新长回来。
"""
import json
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "window_controller_gateway"

# 显式例外：处理器仍在（test_services_failfast 直接调 handle_migrate_devices），
# 但注册被注释禁用（services.py「若需重新启用，取消注释即可」）。重新启用时
# 必须同步 services.yaml，届时把本集合清空即可。
DISABLED_BUT_DOCUMENTED = {"migrate_devices"}


def _locales() -> dict:
    out = {}
    for name in ("strings.json", "translations/zh-CN.json"):
        out[name] = set(json.loads(
            (PKG / name).read_text(encoding="utf-8")).get("services", {}))
    return out


def _yaml_services() -> set:
    return set(re.findall(
        r"^([a-z_]+):\s*$", (PKG / "services.yaml").read_text(encoding="utf-8"), re.M))


class TestServiceCatalogTriple:
    def test_locales_symmetric(self):
        loc = _locales()
        assert len(set(map(frozenset, loc.values()))) == 1, (
            f"双语服务键集合不等：{ {k: sorted(v) for k, v in loc.items()} }"
        )

    def test_every_yaml_service_has_bilingual_text(self):
        loc = _locales()
        yaml_keys = _yaml_services()
        assert yaml_keys, "services.yaml 解析为空（守卫会瞎）"
        for name, keys in loc.items():
            missing = yaml_keys - keys
            assert not missing, (
                f"{name} 缺服务文案 {sorted(missing)}——HA 服务页会裸显 key"
            )

    def test_extra_text_is_only_explicit_whitelist(self):
        loc = _locales()
        extras = set.intersection(*loc.values()) - _yaml_services()
        assert extras == DISABLED_BUT_DOCUMENTED, (
            f"strings 里有未登记的服务文案 {sorted(extras - DISABLED_BUT_DOCUMENTED)}，"
            f"或白名单已过期 {sorted(DISABLED_BUT_DOCUMENTED - extras)}——"
            "孤儿文案与缺文案同罪"
        )

    def test_unignore_gateway_present_in_all_three(self):
        """自救出口必须三方在场（它是「误点忽略」后唯一恢复路径）。"""
        assert "unignore_gateway" in _yaml_services()
        for name, keys in _locales().items():
            assert "unignore_gateway" in keys, f"{name} 缺 unignore_gateway 文案"
