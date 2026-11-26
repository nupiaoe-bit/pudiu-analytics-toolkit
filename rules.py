# -*- coding: utf-8 -*-
"""字段提取规则引擎：从响应 JSON 中扫描目标字段，套前后缀生成地址/文本。"""
import json
import os
import sys


def data_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


RULES_FILE = os.path.join(data_dir(), "rules.json")


def default_rules_file():
    return RULES_FILE


def load_rules():
    try:
        if os.path.exists(RULES_FILE):
            with open(RULES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_rules(rules):
    try:
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def extract_values(obj, target_key, case_insensitive=True):
    """递归扫描 JSON 中所有名为 target_key 的字段值，返回字符串列表。"""
    if not target_key:
        return []
    out = []
    target = str(target_key).lower() if case_insensitive else str(target_key)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                ks = str(k).lower() if case_insensitive else str(k)
                if ks == target and v is not None:
                    if isinstance(v, (str, int, float, bool)):
                        out.append(str(v))
                    elif isinstance(v, (list, dict)):
                        out.append(json.dumps(v, ensure_ascii=False))
                walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(obj)
    return out


def parse_loose(text):
    """宽松解析响应正文：兼容 JSONP(回调包裹)、尾部分号、BOM。返回 (是否成功, 数据)。"""
    s = (text or "").strip().lstrip("\ufeff")
    if not s:
        return False, None
    candidates = [s]
    # callback({...}) / callback([...]); 形式
    lp = s.find("(")
    rp = s.rfind(")")
    if 0 <= lp < rp:
        candidates.insert(0, s[lp + 1:rp])
    # 裸括号包裹
    if s.startswith("(") and s.endswith(")"):
        candidates.insert(0, s[1:-1])
    # 去掉结尾分号
    if s.endswith(";"):
        candidates.insert(0, s[:-1])
    for c in candidates:
        try:
            return True, json.loads(c)
        except Exception:
            continue
    return False, None


def apply_rule_to_text(text, rule):
    """把一条响应正文套用规则，返回生成的字符串列表。"""
    if not rule.get("enabled", True):
        return []
    key = (rule.get("target_key") or "").strip()
    if not key:
        return []
    ok, data = parse_loose(text)
    if not ok:
        return []
    vals = extract_values(data, key, rule.get("case_insensitive", True))
    prefix = rule.get("prefix", "") or ""
    suffix = rule.get("suffix", "") or ""
    result = []
    for v in vals:
        result.append(prefix + v + suffix)
    return result


def rule_matches(rule, rec):
    """判断某条请求是否匹配规则的 URL 关键字 + 方法条件。"""
    if not rule.get("enabled", True):
        return False
    kw = (rule.get("url_match") or "").strip()
    if kw:
        # 支持逗号分隔多个关键字，任一命中即可
        keywords = [k.strip() for k in kw.split(",") if k.strip()]
        if keywords and not any(k.lower() in (rec.get("url") or "").lower() for k in keywords):
            return False
    method = (rule.get("method") or "").strip().upper()
    if method and rec.get("method", "").upper() != method:
        return False
    return True
