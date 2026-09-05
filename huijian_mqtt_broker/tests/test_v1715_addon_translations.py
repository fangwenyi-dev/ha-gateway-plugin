# -*- coding: utf-8 -*-
"""v1.7.15 钉桩：Supervisor 配置表单本地化文件与 schema 双向同步。

机制（一手源码实证，supervisor 2025.12.3）：
  store/data.py::_read_addon_translations 读 <加载项目录>/translations/
  <语言代码>.yaml，经 addons/validate.py::SCHEMA_ADDON_TRANSLATIONS 校验
  ——configuration.<键> 的 name 为 **必填**，缺失条目会被 validate 整体
  拒掉该文件（try/except warning，不炸但全语言静默失效）。
本测试防三种漂移：
  1) schema 新增配置项、翻译文件漏条  → Supervisor 该字段回退英文键名；
  2) 翻译文件引用 schema 不存在的键   → 幽灵文案；
  3) 条目缺 name（SCHEMA_REQUIRED）   → 整文件被拒、全部字段一起失语。
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG = (ROOT / "config.yaml").read_text(encoding="utf-8")
TRANS = ROOT / "translations"

REQUIRED_LANGS = ["zh-Hans.yaml", "zh-CN.yaml", "en.yaml"]


def _schema_keys():
    m = re.search(r"^schema:\n(.*?)(?=^\S|\Z)", CFG, re.M | re.S)
    assert m, "config.yaml schema 块锚丢失"
    return [km.group(1) for line in m.group(1).splitlines()
            if (km := re.match(r"[ \t]+(\w+):", line))]


def test_translation_files_exist_and_parse():
    for name in REQUIRED_LANGS:
        p = TRANS / name
        assert p.is_file(), f"缺 translations/{name}"
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert isinstance(d, dict) and "configuration" in d, \
            f"{name} 缺 configuration 顶层键"


def test_translation_keys_match_schema_exactly():
    keys = set(_schema_keys())
    for name in REQUIRED_LANGS:
        d = yaml.safe_load((TRANS / name).read_text(encoding="utf-8"))
        tkeys = set(d["configuration"])
        assert tkeys == keys, \
            f"{name} 与 schema 漂移：漏={keys - tkeys} 幽灵={tkeys - keys}"


def test_every_entry_has_name_and_description():
    # Supervisor SCHEMA_TRANSLATION_CONFIGURATION：name 必填（缺=整文件拒），
    # description 选填但本项目全部要求给（用户诉求就是解释英文键名）
    for name in REQUIRED_LANGS:
        d = yaml.safe_load((TRANS / name).read_text(encoding="utf-8"))
        for k, v in d["configuration"].items():
            assert isinstance(v, dict) and v.get("name"), \
                f"{name}:{k} 缺必填 name——会导致整份翻译被 Supervisor 拒收"
            assert v.get("description"), f"{name}:{k} 缺 description"


def test_zh_files_are_chinese_and_identical():
    zh = (TRANS / "zh-Hans.yaml").read_text(encoding="utf-8")
    cn = (TRANS / "zh-CN.yaml").read_text(encoding="utf-8")
    d = yaml.safe_load(zh)
    first = d["configuration"]["username"]["name"]
    assert re.search(r"[\u4e00-\u9fff]", first), "zh-Hans 正文不是中文"
    assert zh == cn, "zh-CN 兜底与 zh-Hans 不同文（应逐字一致）"
