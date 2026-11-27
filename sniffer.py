# -*- coding: utf-8 -*-
"""
被动抓包引擎
用 Playwright 启动有头 Chrome，通过 CDP Network 域监听所有请求/响应。
用户在浏览器里正常访问网页，引擎在后台记录明文请求/响应。
"""
import base64
import json
import queue
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

import rules as rules_mod
import screenutil

# 需要读取正文的 MIME 类型（跳过图片/字体/视频等二进制）
TEXT_HINTS = ("json", "javascript", "xml", "html", "text", "form-urlencoded", "graphql", "plain")


def is_text_mime(mime):
    m = (mime or "").lower()
    return any(h in m for h in TEXT_HINTS)


def parse_cookie_header(value):
    """解析 Cookie 请求头 'a=1; b=2' -> [{'name':..,'value':..}]"""
    out = []
    if not value:
        return out
    for part in str(value).split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out.append({"name": k.strip(), "value": v.strip()})
    return out


def parse_set_cookie(value):
    """解析 Set-Cookie 响应头，可能多条用换行拼接。"""
    out = []
    if not value:
        return out
    chunks = str(value).replace("\r", "\n").split("\n")
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        first = chunk.split(";", 1)[0]
        k, v = first.split("=", 1)
        item = {"name": k.strip(), "value": v.strip(), "raw": chunk[:500]}
        low = chunk.lower()
        if "httponly" in low:
            item["httpOnly"] = True
        if "secure" in low:
            item["secure"] = True
        for attr in ("path", "domain", "samesite"):
            marker = attr + "="
            idx = low.find(marker)
            if idx >= 0:
                val = chunk[idx + len(marker):].split(";", 1)[0].strip()
                item[attr] = val
        out.append(item)
    return out


def header_get(headers, name):
    """大小写不敏感地取 header 值"""
    if not headers:
        return ""
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return ""


class Sniffer:
    def __init__(self, log_cb=None):
        self.log_cb = log_cb or (lambda m: None)
        self._lock = threading.RLock()
        self.records = []            # 抓到的请求列表
        self._seq = 0                # 自增序号
        self._by_rid = {}            # requestId -> record（跨页面共享 key 可能重复，加页面标识）
        self._running = False
        self._stop = threading.Event()
        self._thread = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._cdp_sessions = []
        self._cdp_by_tag = {}   # tag -> cdp session（供重新提取历史时重试取正文）
        self._capture_body = True
        self._owns_browser = True
        self._attach_port = 0
        self._diag = {"responses": 0, "body_ok": 0, "body_fail": 0,
                      "json_ok": 0, "json_fail": 0, "matched": 0, "no_key": 0,
                      "errors": []}
        self._extra_req = {}   # requestId(key) -> 关联 Cookie（extraInfo 可能早于 request 到达）
        self._cmd_q = queue.Queue()   # 主线程 -> 浏览器线程的命令队列
        self._result_q = queue.Queue()
        # 规则引擎
        self.rules = rules_mod.load_rules()
        self.generated = []          # 自动生成的地址/文本结果
        self._gen_seq = 0
        self._gen_seen = set()

    def _log(self, m):
        try:
            self.log_cb(str(m))
        except Exception:
            pass

    @property
    def running(self):
        return self._running

    def start(self, headless=False, attach_port=0):
        if self._running:
            return "抓包已在运行"
        self._stop.clear()
        self._attach_port = int(attach_port or 0)
        self._thread = threading.Thread(target=self._loop,
                                        args=(headless, self._attach_port), daemon=True)
        self._thread.start()
        # 等待浏览器就绪
        for _ in range(150):
            if self._page is not None:
                if self._attach_port:
                    return f"已附加到 Chrome 调试端口 {self._attach_port}，可直接在已打开的窗口里浏览"
                return "抓包已启动，请在弹出的窗口中访问网页"
            if not self._thread.is_alive():
                return "启动失败，请查看 startup.log"
            time.sleep(0.1)
        return "启动超时，请重试"

    def _loop(self, headless, attach_port=0):
        page = None
        try:
            self._pw = sync_playwright().start()
            if attach_port:
                # 附加到用户已启动的 Chrome（必须带 --remote-debugging-port）
                self._owns_browser = False
                self._browser = self._pw.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{attach_port}", timeout=15000)
                self._context = self._browser.contexts[0] if self._browser.contexts else None
                if not self._context:
                    raise RuntimeError("调试浏览器中没有可用上下文")
                pages = [p for p in self._context.pages if not p.is_closed()]
                for pg in pages:
                    self._attach(pg)
                page = pages[0] if pages else None
                self._page = page
                self._log(f"已附加调试端口 {attach_port}，现有标签 {len(pages)} 个")
            else:
                self._owns_browser = True
                # 关键：把窗口位置/尺寸限制在当前屏幕工作区内，避免窗口跑到屏幕外看不见
                win_args = screenutil.chrome_window_args("browser") if not headless else []
                self._browser = self._pw.chromium.launch(
                    channel="chrome", headless=headless,
                    args=["--disable-blink-features=AutomationControlled", "--no-first-run"] + win_args)
                self._context = self._browser.new_context(ignore_https_errors=True)
                page = self._context.new_page()
                self._page = page
                self._attach(page)
                self._log("抓包已启动")
                try:
                    page.goto("about:blank")
                except Exception:
                    pass
            # 新标签页也自动监听
            self._context.on("page", self._on_new_page)
            self._running = True
            # 保持事件循环运转 + 处理来自界面的命令（必须在浏览器线程执行）
            while not self._stop.is_set():
                try:
                    cmd, payload = self._cmd_q.get_nowait()
                except queue.Empty:
                    cmd = None
                if cmd == "goto":
                    url = payload
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    try:
                        alive = [p for p in self._context.pages if not p.is_closed()]
                        target = self._page if self._page and not self._page.is_closed() else (alive[0] if alive else self._context.new_page())
                        target.goto(url, wait_until="domcontentloaded", timeout=30000)
                        self._result_q.put(f"已打开：{url}")
                    except Exception as e:
                        self._result_q.put(f"打开失败：{e}")
                elif cmd == "stop":
                    break
                # 当前页可能被用户关掉，换一个可用的页维持事件循环
                if not page or page.is_closed():
                    alive = [p for p in self._context.pages if not p.is_closed()]
                    page = alive[0] if alive else self._context.new_page()
                    self._page = page
                try:
                    page.wait_for_timeout(150)
                except Exception:
                    if self._stop.is_set():
                        break
                    time.sleep(0.2)
        except Exception as e:
            self._log(f"抓包引擎异常: {e}")
        finally:
            self._running = False
            for cdp in list(self._cdp_sessions):
                try:
                    cdp.detach()
                except Exception:
                    pass
            try:
                # 附加模式下只断开连接，不关闭用户自己的 Chrome
                if self._owns_browser and self._browser:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

    def _on_new_page(self, page):
        try:
            self._attach(page)
            self._log(f"已监听新标签页: {page.url[:50]}")
        except Exception as e:
            self._log(f"新标签页监听失败: {e}")

    def _attach(self, page):
        cdp = self._context.new_cdp_session(page)
        # 缓冲区调大，避免响应体被 CDP 截断；禁用缓存，否则缓存命中的请求
        # 在 loadingFinished 后 getResponseBody 会报 "No resource with given identifier found"
        cdp.send("Network.enable", {
            "maxTotalBufferSize": 100000000,
            "maxResourceBufferSize": 50000000,
        })
        try:
            cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        except Exception:
            pass
        tag = id(cdp)
        self._cdp_sessions.append(cdp)
        self._cdp_by_tag[str(tag)] = cdp
        # 用闭包绑定每个 session 的 tag，避免多标签 requestId 冲突
        cdp.on("Network.requestWillBeSent", lambda p, t=tag: self._on_request(p, t))
        cdp.on("Network.requestWillBeSentExtraInfo", lambda p, t=tag: self._on_request_extra(p, t))
        cdp.on("Network.responseReceived", lambda p, t=tag: self._on_response(p, t))
        cdp.on("Network.loadingFinished", lambda p, t=tag, c=cdp: self._on_finished(p, t, c))
        cdp.on("Network.loadingFailed", lambda p, t=tag: self._on_failed(p, t))

    def _new_key(self, tag, rid):
        return f"{tag}:{rid}"

    def _on_request_extra(self, prm, tag):
        """CDP 的 extraInfo 带真实 Cookie（requestWillBeSent 里 Chrome 不暴露 Cookie 头）。
        该事件可能早于 requestWillBeSent，故先缓存，等记录建立时合并。"""
        key = self._new_key(tag, prm.get("requestId", ""))
        associated = prm.get("associatedCookies", []) or []
        cookies = []
        for item in associated:
            c = item.get("cookie", {}) if isinstance(item, dict) else {}
            if c.get("name"):
                cookies.append({
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", ""),
                    "httpOnly": bool(c.get("httpOnly")),
                    "secure": bool(c.get("secure")),
                    "session": bool(c.get("session")),
                })
        # 也解析 headers 里的 cookie 作为补充
        hdr_cookie = header_get(prm.get("headers", {}), "cookie")
        from_hdr = parse_cookie_header(hdr_cookie)
        if from_hdr:
            names = {c["name"] for c in cookies}
            for c in from_hdr:
                if c["name"] not in names:
                    cookies.append(c)
        with self._lock:
            rec = self._by_rid.get(key)
            if rec:
                if cookies:
                    rec["req_cookies"] = cookies
            else:
                self._extra_req[key] = cookies

    def _on_request(self, prm, tag):
        if self._stop.is_set():
            return
        req = prm.get("request", {})
        url = req.get("url", "")
        if not url.startswith(("http://", "https://")):
            return
        rid = prm.get("requestId", "")
        parsed = urlparse(url)
        req_headers = req.get("headers", {})
        with self._lock:
            self._seq += 1
            rec = {
                "id": self._seq,
                "time": datetime.now().strftime("%H:%M:%S"),
                "method": req.get("method", ""),
                "status": 0,
                "url": url,
                "host": parsed.netloc,
                "path": parsed.path or "/",
                "type": prm.get("type", ""),
                "mime": "",
                "size": 0,
                "duration": 0,
                "req_headers": req_headers,
                "req_body": req.get("postData", "") or "",
                "resp_headers": {},
                "resp_body": "",
                "req_cookies": parse_cookie_header(header_get(req_headers, "cookie")),
                "resp_set_cookies": [],
                "_ts": prm.get("timestamp", 0),
                "_key": self._new_key(tag, rid),
                "_rid": rid,
            }
            # 合并可能早到的 extraInfo Cookie
            cached = self._extra_req.pop(rec["_key"], None)
            if cached:
                rec["req_cookies"] = cached
            self.records.append(rec)
            self._by_rid[rec["_key"]] = rec

    def _on_response(self, prm, tag):
        resp = prm.get("response", {})
        key = self._new_key(tag, prm.get("requestId", ""))
        with self._lock:
            self._diag["responses"] += 1
            rec = self._by_rid.get(key)
            if not rec:
                return
            rec["status"] = resp.get("status", 0)
            rec["mime"] = resp.get("mimeType", "")
            rec["resp_headers"] = resp.get("headers", {})
            if "set-cookie" in rec["resp_headers"] or "Set-Cookie" in rec["resp_headers"]:
                rec["resp_set_cookies"] = parse_set_cookie(header_get(rec["resp_headers"], "set-cookie"))
            if prm.get("type"):
                rec["type"] = prm["type"]

    def _get_body_with_retry(self, cdp, rid, tries=3):
        """CDP 取正文偶发 'No resource with given identifier found'（缓存/时序），重试几次。"""
        last = None
        for i in range(tries):
            try:
                return cdp.send("Network.getResponseBody", {"requestId": rid})
            except Exception as e:
                last = e
                time.sleep(0.08 * (i + 1))
        raise last

    def _on_finished(self, prm, tag, cdp):
        key = self._new_key(tag, prm.get("requestId", ""))
        rid = prm.get("requestId", "")
        with self._lock:
            rec = self._by_rid.get(key)
            if not rec:
                return
            rec["size"] = prm.get("encodedDataLength", 0) or 0
            ts0 = rec.get("_ts", 0)
            rec["duration"] = round((prm.get("timestamp", ts0) - ts0) * 1000, 1)
            mime = rec["mime"]
            # 即使 MIME 不常见，只要匹配了某条规则也尝试取正文（有些站点 JSON 返回 octet-stream）
            rule_hit = any(rules_mod.rule_matches(r, rec) for r in self.rules)
            if not self._capture_body or (not is_text_mime(mime) and not rule_hit):
                return
        # 在锁外取正文，避免阻塞事件回调
        if rec["size"] > 5 * 1024 * 1024:
            with self._lock:
                rec["resp_body"] = "[响应过大，已跳过正文]"
            return
        try:
            body = self._get_body_with_retry(cdp, rid)
            text = body.get("body", "") or ""
            if body.get("base64Encoded"):
                try:
                    text = base64.b64decode(text).decode("utf-8", "replace")
                except Exception:
                    text = "[二进制内容]"
            with self._lock:
                rec["resp_body"] = text[:500000]  # 单条最多保存 500KB 文本
                rec["_body_err"] = ""
                self._diag["body_ok"] += 1
            # 规则引擎：自动对该响应应用匹配的规则
            try:
                self._apply_rules(rec)
            except Exception as e:
                self._log(f"规则处理异常: {e}")
        except Exception as e:
            with self._lock:
                rec["resp_body"] = ""
                rec["_body_err"] = str(e)[:120]
                self._diag["body_fail"] += 1
                errs = self._diag["errors"]
                errs.append(f"{rec.get('path', '')} : {str(e)[:80]}")
                if len(errs) > 8:
                    del errs[0]
            self._log(f"正文读取失败 {rec.get('path', '')}: {str(e)[:80]}")

    def _on_failed(self, prm, tag):
        key = self._new_key(tag, prm.get("requestId", ""))
        with self._lock:
            rec = self._by_rid.get(key)
            if rec:
                rec["status"] = -1
                rec["resp_body"] = "[失败] " + (prm.get("errorText", "") or "")

    # ---------- 规则引擎 ----------
    def _apply_rules(self, rec):
        """对一条记录应用所有匹配的规则，生成结果累积去重"""
        body = rec.get("resp_body") or ""
        # 只跳过我们自己写入的占位文本，不能跳过 JSON 数组响应
        if not body or body.startswith("[响应过大") or body.startswith("[失败]"):
            return
        with self._lock:
            matched = [r for r in self.rules if rules_mod.rule_matches(r, rec)]
        if not matched:
            return
        with self._lock:
            self._diag["matched"] += 1
        # 链接模式（页面链接 / sitemap）直接处理 HTML/XML 正文；字段模式仍需 JSON
        link_modes = {"links", "sitemap"}
        has_link_rule = any((r.get("mode", "field") or "field") in link_modes for r in matched)
        has_field_rule = any((r.get("mode", "field") or "field") not in link_modes for r in matched)
        ok = False
        if has_field_rule:
            ok, _data = rules_mod.parse_loose(body)
            if not ok:
                with self._lock:
                    self._diag["json_fail"] += 1
                    errs = self._diag["errors"]
                    errs.append(f"非JSON响应 {rec.get('path', '')} : {body[:50]}")
                    if len(errs) > 8:
                        del errs[0]
            else:
                with self._lock:
                    self._diag["json_ok"] += 1
        if not ok and not has_link_rule:
            return
        added = 0
        for rule in matched:
            # 字段模式若正文非 JSON 则跳过；链接模式不受影响
            if (rule.get("mode", "field") or "field") not in link_modes and not ok:
                continue
            values = rules_mod.apply_rule_to_text(body, rule, base_url=rec.get("url", ""))
            if not values:
                with self._lock:
                    self._diag["no_key"] += 1
                self._log(f"规则「{rule.get('name','')}」未在响应中找到字段 {rule.get('target_key','')}")
            for v in values:
                with self._lock:
                    key = (rule.get("name", ""), v)
                    if rule.get("dedupe", True) and key in self._gen_seen:
                        continue
                    self._gen_seen.add(key)
                    self._gen_seq += 1
                    self.generated.append({
                        "id": self._gen_seq,
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "rule": rule.get("name", ""),
                        "key": rule.get("target_key", ""),
                        "value": v.replace(rule.get("prefix", "") or "", "", 1)
                                  .replace(rule.get("suffix", "") or "", "", 1).strip(),
                        "output": v,
                        "source_url": rec.get("url", ""),
                        "source_id": rec.get("id", 0),
                    })
                    added += 1
        if added:
            self._log(f"规则提取 +{added} 条")

    def set_rules(self, rules):
        """保存规则配置（前端传来的完整列表）"""
        if not isinstance(rules, list):
            return "规则格式错误"
        self.rules = rules
        ok = rules_mod.save_rules(rules)
        n = sum(1 for r in rules if r.get("enabled", True))
        return f"已保存 {len(rules)} 条规则（启用 {n} 条）" + ("" if ok else "（配置文件写入失败）")

    def get_rules(self):
        return self.rules

    def get_generated(self, since_id=0):
        with self._lock:
            items = [g for g in self.generated if g["id"] > since_id]
        return [dict(g) for g in items]

    def clear_generated(self):
        with self._lock:
            self.generated = []
            self._gen_seen = set()
            self._gen_seq = 0
        return "生成结果已清空"

    def reprocess(self):
        """对已抓到的所有记录重新跑一遍规则；正文为空的再尝试向浏览器补取一次。"""
        with self._lock:
            recs = list(self.records)
        before = len(self.generated)
        refetched = 0
        for rec in recs:
            if not rec.get("resp_body") and rec.get("_rid"):
                tag = str(rec.get("_key", "")).split(":", 1)[0]
                cdp = self._cdp_by_tag.get(tag)
                if cdp:
                    try:
                        body = self._get_body_with_retry(cdp, rec["_rid"], tries=2)
                        text = body.get("body", "") or ""
                        if body.get("base64Encoded"):
                            text = base64.b64decode(text).decode("utf-8", "replace")
                        if text:
                            rec["resp_body"] = text[:500000]
                            rec["_body_err"] = ""
                            refetched += 1
                    except Exception:
                        pass
            if rec.get("resp_body"):
                try:
                    self._apply_rules(rec)
                except Exception:
                    pass
        return f"重新处理完成，补取正文 {refetched} 条，新增 {len(self.generated) - before} 条"

    def get_diag(self):
        """给界面展示的诊断信息：为什么翻页后生成结果可能是 0。"""
        with self._lock:
            d = dict(self._diag)
            d["errors"] = list(d["errors"])
            d["records"] = len(self.records)
            d["with_body"] = sum(1 for r in self.records if r.get("resp_body"))
            d["generated"] = len(self.generated)
        return d

    def apply_rule_to_record(self, rec_id, rule_index):
        """手动对某条记录应用指定规则"""
        with self._lock:
            rec = next((r for r in self.records if r["id"] == rec_id), None)
            rule = self.rules[rule_index] if 0 <= rule_index < len(self.rules) else None
        if not rec or not rule:
            return 0
        before = len(self.generated)
        vals = rules_mod.apply_rule_to_text(rec.get("resp_body", ""), rule, base_url=rec.get("url", ""))
        for v in vals:
            with self._lock:
                key = (rule.get("name", ""), v)
                if key in self._gen_seen:
                    continue
                self._gen_seen.add(key)
                self._gen_seq += 1
                self.generated.append({
                    "id": self._gen_seq,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "rule": rule.get("name", ""),
                    "key": rule.get("target_key", ""),
                    "value": v,
                    "output": v,
                    "source_url": rec.get("url", ""),
                    "source_id": rec.get("id", 0),
                })
        return len(self.generated) - before

    # ---------- 对外接口 ----------
    def goto(self, url):
        if not self._page:
            return "请先启动浏览器"
        url = url.strip()
        if not url:
            return "网址不能为空"
        # 命令发给浏览器线程执行，并等待结果
        self._cmd_q.put(("goto", url))
        try:
            return self._result_q.get(timeout=40)
        except queue.Empty:
            return "打开超时"

    def clear(self):
        with self._lock:
            self.records = []
            self._by_rid = {}
            self._extra_req = {}
            self._seq = 0
            self._diag = {"responses": 0, "body_ok": 0, "body_fail": 0,
                          "json_ok": 0, "json_fail": 0, "matched": 0, "no_key": 0,
                          "errors": []}
        return "请求记录已清空（生成结果保留）"

    def set_capture_body(self, enabled):
        self._capture_body = bool(enabled)
        return "已开启正文抓取" if enabled else "已关闭正文抓取（仅记录元信息）"

    @staticmethod
    def _public(rec):
        """内部记录 -> 界面用 dict（保留可读的正文错误提示）"""
        d = dict(rec)
        for k in list(d.keys()):
            if k.startswith("_"):
                d.pop(k, None)
        d["body_error"] = rec.get("_body_err", "") or ""
        d["has_body"] = bool(rec.get("resp_body"))
        return d

    def get_records(self, since_id=0, limit=0):
        """增量拉取记录，供界面轮询"""
        with self._lock:
            items = [r for r in self.records if r["id"] > since_id]
        if limit and len(items) > limit:
            items = items[-limit:]
        return [self._public(r) for r in items]

    def get_detail(self, rec_id):
        with self._lock:
            for r in self.records:
                if r["id"] == rec_id:
                    return self._public(r)
        return None

    def update_body(self, rec_id, text, field="resp"):
        """用户在界面里手动编辑正文/请求体：只改内存中的记录，立即对所有面板生效。"""
        with self._lock:
            rec = next((r for r in self.records if r["id"] == int(rec_id)), None)
            if not rec:
                return None
            key = "req_body" if field == "req" else "resp_body"
            rec[key] = str(text or "")
            if key == "resp_body":
                rec["_body_err"] = ""
            return self._public(rec)

    def update_generated(self, gen_id, text):
        """用户手动修改生成结果（地址/文本），改完立刻同步到前端与导出。"""
        with self._lock:
            g = next((x for x in self.generated if x["id"] == int(gen_id)), None)
            if not g:
                return None
            g["output"] = str(text or "")
            return dict(g)

    def fetch_body(self, rec_id):
        """前端点击地址时按需重新取一次响应正文（CDP 缓存可能让首次取失败）。

        返回最新记录 dict；失败时返回带 fetch_error 的记录，界面可以明确提示。
        """
        with self._lock:
            rec = next((r for r in self.records if r["id"] == rec_id), None)
        if not rec:
            return None
        rid = rec.get("_rid", "")
        tag = str(rec.get("_key", "")).split(":", 1)[0]
        cdp = self._cdp_by_tag.get(tag)
        if not rid or not cdp:
            d = self._public(rec)
            d["fetch_error"] = "浏览器会话已断开，无法补取正文"
            return d
        try:
            body = self._get_body_with_retry(cdp, rid, tries=3)
            text = body.get("body", "") or ""
            if body.get("base64Encoded"):
                try:
                    text = base64.b64decode(text).decode("utf-8", "replace")
                except Exception:
                    text = "[二进制内容]"
            with self._lock:
                rec["resp_body"] = text[:500000]
                rec["_body_err"] = ""
                self._diag["body_ok"] += 1
            return self._public(rec)
        except Exception as e:
            d = self._public(rec)
            d["fetch_error"] = str(e)[:160]
            with self._lock:
                rec["_body_err"] = str(e)[:120]
                self._diag["body_fail"] += 1
            return d

    def sample_keys(self, rec_id):
        """给规则编辑器用：列出某条响应 JSON 里出现过的所有字段名。"""
        with self._lock:
            rec = next((r for r in self.records if r["id"] == rec_id), None)
        if not rec:
            return []
        ok, data = rules_mod.parse_loose(rec.get("resp_body", ""))
        if not ok:
            return []
        keys, seen = [], set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    ks = str(k)
                    if ks not in seen:
                        seen.add(ks)
                        keys.append(ks)
                    walk(v)
            elif isinstance(o, list):
                for item in o:
                    walk(item)

        walk(data)
        return keys[:200]

    def preview_rule(self, rule, rec_id):
        """规则试运行：返回该规则在这条响应上生成的所有值。"""
        with self._lock:
            rec = next((r for r in self.records if r["id"] == rec_id), None)
        if not rec or not isinstance(rule, dict):
            return []
        return rules_mod.apply_rule_to_text(rec.get("resp_body", ""), rule, base_url=rec.get("url", ""))

    def count(self):
        with self._lock:
            return len(self.records)

    def stop(self):
        attached = bool(self._attach_port)
        self._stop.set()
        self._running = False
        return "已断开附加，抓包停止（你的 Chrome 保持打开）" if attached else "浏览器已关闭，抓包停止"


if __name__ == "__main__":
    import sys
    s = Sniffer(log_cb=lambda m: print("LOG:", m))
    print(s.start(headless=True))
    s.goto("https://www.crccep.cn/")
    time.sleep(5)
    rows = s.get_records()
    print("抓到", len(rows), "条")
    for r in rows[:5]:
        print(r["id"], r["method"], r["status"], r["type"], r["url"][:70], "body=", len(r["resp_body"]))
    s.stop()
