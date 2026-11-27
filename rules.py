# -*- coding: utf-8 -*-
"""规则引擎：从响应正文中提取字段 / 页面链接 / 站点地图链接，套前后缀生成地址/文本。"""
import json
import os
import re
import sys
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


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


class _LinkHTMLParser(HTMLParser):
    """从 HTML 中收集 a/link/area 的 href 与 img/script/iframe 的 src。"""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        want = {"href"} if tag in ("a", "link", "area") else ({"src"} if tag in ("img", "script", "iframe", "source") else set())
        if not want:
            return
        for k, v in attrs:
            if k and k.lower() in want and v:
                self.links.append(v.strip())


def extract_html_links(text):
    """解析 HTML 正文，返回原始链接字符串列表（含相对链接、锚点）。"""
    p = _LinkHTMLParser()
    try:
        p.feed(text or "")
        p.close()
    except Exception:
        pass
    # 兜底：正则抓 <a href=...>，防止畸形 HTML 让解析器漏掉
    for m in re.finditer(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", text or "", re.I | re.S):
        p.links.append(m.group(1).strip())
    return p.links


def extract_sitemap_locs(text):
    """解析 sitemap XML / txt，返回 <loc> 或纯文本 URL 列表。"""
    out = []
    for m in re.finditer(r"<loc>\s*(.*?)\s*</loc>", text or "", re.I | re.S):
        out.append(unescape(m.group(1)).strip())
    if not out:
        # sitemap.txt：一行一个 URL
        for line in (text or "").splitlines():
            s = line.strip()
            if s.startswith(("http://", "https://")):
                out.append(s)
    return out


def normalize_link(raw, base_url="", rule=None):
    """把一条原始链接规范化为绝对地址；按规则过滤。返回地址或空串。"""
    rule = rule or {}
    s = unescape((raw or "").strip())
    if not s or s.startswith("#"):
        return ""
    low = s.lower()
    if low.startswith(("javascript:", "mailto:", "tel:", "data:", "about:")):
        return ""
    if base_url and not low.startswith(("http://", "https://")):
        s = urljoin(base_url, s)
    # include：逗号分隔，任一命中即保留
    inc = [x.strip().lower() for x in str(rule.get("link_include", "") or "").split(",") if x.strip()]
    if inc and not any(x in s.lower() for x in inc):
        return ""
    # exclude：逗号分隔，任一命中即丢弃
    exc = [x.strip().lower() for x in str(rule.get("link_exclude", "") or "").split(",") if x.strip()]
    if exc and any(x in s.lower() for x in exc):
        return ""
    if rule.get("link_full_url") and not s.lower().startswith(("http://", "https://")):
        return ""
    if rule.get("link_same_host") and base_url:
        try:
            if urlparse(s).netloc and urlparse(s).netloc != urlparse(base_url).netloc:
                return ""
        except Exception:
            pass
    return s


def apply_links_rule(text, rule, base_url=""):
    """从 HTML / sitemap 正文提取并规范化链接，返回去重后的地址列表。"""
    mode = rule.get("mode", "field")
    if mode == "sitemap":
        raws = extract_sitemap_locs(text)
    else:  # links
        raws = extract_html_links(text)
    out, seen = [], set()
    for raw in raws:
        u = normalize_link(raw, base_url, rule)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    if rule.get("link_max"):
        try:
            out = out[:max(1, int(rule["link_max"]))]
        except Exception:
            pass
    return out


def apply_rule_to_text(text, rule, base_url=""):
    """把一条响应正文套用规则，返回生成的字符串列表。"""
    if not rule.get("enabled", True):
        return []
    mode = rule.get("mode", "field") or "field"
    prefix = rule.get("prefix", "") or ""
    suffix = rule.get("suffix", "") or ""
    if mode == "links" or mode == "sitemap":
        # 链接模式下前后缀默认留空；如用户填写则套在链接外侧
        return [prefix + v + suffix for v in apply_links_rule(text, rule, base_url)]
    key = (rule.get("target_key") or "").strip()
    if not key:
        return []
    ok, data = parse_loose(text)
    if not ok:
        return []
    vals = extract_values(data, key, rule.get("case_insensitive", True))
    return [prefix + v + suffix for v in vals]


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
