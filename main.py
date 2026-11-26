# -*- coding: utf-8 -*-
"""Pudiu 大数据分析可视化工具 · 主程序（pywebview 桌面界面）"""
import os
import sys
import json
import threading
import subprocess
import tempfile
import webbrowser
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import webview
from sniffer import Sniffer
from exporter import do_export, export_generated
from cliputil import set_clipboard, get_clipboard
import rules as rules_mod
import screenutil

# 必须在创建任何窗口前设置，否则缩放屏幕上坐标会被虚拟放大导致窗口跑偏
screenutil.make_dpi_aware()

APP_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "4.1"
APP_NAME = "Pudiu 大数据分析可视化工具"

# 预设网址书签（首次运行写入 bookmarks.json，之后以用户修改为准）
DEFAULT_BOOKMARKS = [
    {"name": "tool.pudiu.com", "url": "https://tool.pudiu.com/"},
    {"name": "bing.com", "url": "https://bing.com"},
]

# 工具导航：分类整理的数据分析 / 可视化在线工具（首次运行写入 navtools.json）
NAV_TOOLS = [
    {"name": "Pudiu 工具箱", "cat": "数据分析平台", "url": "https://tool.pudiu.com/",
     "desc": "在线数据处理工具集合，JSON / 文本 / 编码等常用操作一站完成。",
     "tip": "把抓包结果复制进来直接处理，和本软件的「工具」页形成互补。"},
    {"name": "Pudiu JSON 字段提取", "cat": "接口与抓包", "url": "https://url.pudiu.com/post",
     "desc": "粘贴响应 JSON，按字段提取并拼接成新地址。",
     "tip": "本软件的「规则」页已内置同类能力，翻页时会自动累积生成地址。"},
    {"name": "Flourish", "cat": "数据分析平台", "url": "https://flourish.studio/",
     "desc": "把表格数据做成交互式图表、动态排序图与数据故事。",
     "tip": "适合做汇报展示；免费版可导出静态图或嵌入网页。"},
    {"name": "Datawrapper", "cat": "数据分析平台", "url": "https://www.datawrapper.de/",
     "desc": "三步生成可嵌入的响应式图表与地图，无需编程。",
     "tip": "把导出的 CSV 直接拖进去，几分钟出图。"},
    {"name": "RawGraphs", "cat": "数据分析平台", "url": "https://app.rawgraphs.io/",
     "desc": "开源拖拽式数据可视化工具，支持桑基图、树图、弦图等复杂图表。",
     "tip": "粘贴表格数据后选择图表类型，可导出 SVG / PNG。"},
    {"name": "Apache ECharts 示例", "cat": "可视化图表", "url": "https://echarts.apache.org/examples/zh/index.html",
     "desc": "官方图表样例库，含柱状、折线、饼图、地图、关系图等配置项。",
     "tip": "看中哪个效果，点「编辑」直接复制配置代码改数据即可。"},
    {"name": "Chart.js 示例", "cat": "可视化图表", "url": "https://www.chartjs.org/docs/latest/samples/",
     "desc": "轻量 Canvas 图表库的官方示例，适合快速画常规统计图。",
     "tip": "依赖少、上手快，适合嵌到内部系统页面。"},
    {"name": "Highcharts Demo", "cat": "可视化图表", "url": "https://www.highcharts.com/demo",
     "desc": "商业级交互图表演示，甘特图、股票图、地图等效果丰富。",
     "tip": "个人/非商业项目可免费使用，商用需授权。"},
    {"name": "Plotly Chart Studio", "cat": "可视化图表", "url": "https://chart-studio.plotly.com/",
     "desc": "在线绘制统计图表与科学计算可视化，支持 Python / R 数据。",
     "tip": "适合做散点矩阵、3D 曲面等分析型图表。"},
    {"name": "Observable", "cat": "可视化图表", "url": "https://observablehq.com/",
     "desc": "数据可视化笔记本社区，大量可交互、可复用的图表案例。",
     "tip": "搜索字段名或图表类型，常能直接找到现成实现。"},
    {"name": "阿里云 DataV", "cat": "数据分析平台", "url": "https://datav.aliyun.com/",
     "desc": "大屏数据可视化设计工具，内置地图、图表与业务组件。",
     "tip": "适合做监控大屏，部分模板需要登录。"},
    {"name": "ConvertCSV", "cat": "数据清洗转换", "url": "https://www.convertcsv.com/",
     "desc": "CSV / JSON / Excel / SQL 等多种格式互转与清洗。",
     "tip": "本软件导出的 CSV 可在这里快速转成其他格式。"},
    {"name": "JSON.cn", "cat": "数据清洗转换", "url": "https://www.json.cn/",
     "desc": "国内在线 JSON 格式化、校验、转义与压缩工具。",
     "tip": "响应正文复制到这里可快速检查层级结构。"},
    {"name": "JSON Viewer", "cat": "数据清洗转换", "url": "https://jsonviewer.stack.hu/",
     "desc": "树形展示 JSON，折叠展开查看深层字段。",
     "tip": "字段很多时比纯文本更易定位。"},
    {"name": "站长工具", "cat": "数据清洗转换", "url": "https://tool.chinaz.com/",
     "desc": "综合在线工具箱，含编码转换、IP/域名查询、正则测试等。",
     "tip": "国内访问速度较好，适合做日常辅助查询。"},
    {"name": "Regex101", "cat": "文本与正则", "url": "https://regex101.com/",
     "desc": "正则表达式在线编写、测试与解释，支持多语言引擎。",
     "tip": "写「规则」页的匹配关键字前可先在这里验证。"},
    {"name": "RegExr", "cat": "文本与正则", "url": "https://regexr.com/",
     "desc": "交互式正则练习与速查工具，匹配结果实时高亮。",
     "tip": "左侧有常用表达式速查表，适合现查现用。"},
    {"name": "Hoppscotch", "cat": "接口与抓包", "url": "https://hoppscotch.io/",
     "desc": "轻量的 API 请求调试工具，支持 GET/POST、Header、Cookie。",
     "tip": "可把抓包详情页的 cURL 复制过来复现接口。"},
    {"name": "Bing 搜索", "cat": "效率工具", "url": "https://bing.com",
     "desc": "搜索引擎，查接口文档、工具用法与报错信息。",
     "tip": "也是顶部预设网址之一，点一下即可在抓包浏览器打开。"},
]
# 外部数据处理工具（用户可增删改，写入 tools.json）
DEFAULT_TOOLS = [
    {"name": "记事本", "cmd": "notepad.exe {file}", "note": "把选中文本存为临时文件后用记事本打开"},
    {"name": "Python", "cmd": "python {file}", "note": "把选中文本当作 .py 运行（需本机有 python）"},
]


def _json_file(name, default):
    """读取 app 目录下的 JSON 配置，不存在则返回默认值的副本。"""
    path = os.path.join(app_dir(), name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return json.loads(json.dumps(default))


def _save_json_file(name, data):
    path = os.path.join(app_dir(), name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        boot_log(f"保存 {name} 失败: {e}")
        return False


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return APP_DIR


def boot_log(msg):
    try:
        d = app_dir()
        with open(os.path.join(d, "startup.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S} {msg}\n")
    except Exception:
        pass


class Api:
    def __init__(self):
        self.sniffer = Sniffer(log_cb=self._log)
        self._window = None

    def set_window(self, w):
        self._window = w

    def _log(self, msg):
        # 日志只写文件（--windowed 模式无控制台）
        boot_log(str(msg))

    # ---------- 抓包控制 ----------
    def start_browser(self, attach_port=0):
        try:
            return self.sniffer.start(headless=False, attach_port=int(attach_port or 0))
        except Exception as e:
            return f"启动失败：{e}"

    def stop_browser(self):
        return self.sniffer.stop()

    def goto(self, url):
        return self.sniffer.goto(url)

    def set_capture_body(self, enabled):
        return self.sniffer.set_capture_body(enabled)

    def clear_records(self):
        return self.sniffer.clear()

    # ---------- 数据 ----------
    def get_records(self, since_id=0):
        try:
            return self.sniffer.get_records(since_id=int(since_id))
        except Exception:
            return []

    def get_detail(self, rec_id):
        """点地址时强制回源取最新详情：轮询快照里的 resp_body 可能还是空的。"""
        try:
            return self.sniffer.get_detail(int(rec_id))
        except Exception:
            return None

    def fetch_body(self, rec_id):
        """按需从浏览器补取响应正文，解决偶尔 CDP 取正文失败导致看不到数据。"""
        try:
            return self.sniffer.fetch_body(int(rec_id))
        except Exception as e:
            return {"fetch_error": str(e)[:160]}

    def sample_keys(self, rec_id):
        try:
            return self.sniffer.sample_keys(int(rec_id))
        except Exception:
            return []

    def update_body(self, rec_id, text, field="resp"):
        """手动编辑请求体/响应正文（内存生效，重启程序不保留）"""
        try:
            return self.sniffer.update_body(int(rec_id), text, field)
        except Exception:
            return None

    def update_generated(self, gen_id, text):
        """手动修改生成结果（内存生效，导出时采用修改后的内容）"""
        try:
            return self.sniffer.update_generated(int(gen_id), text)
        except Exception:
            return None

    def preview_rule(self, rule, rec_id):
        try:
            return self.sniffer.preview_rule(rule, int(rec_id))
        except Exception:
            return []

    def version(self):
        return VERSION

    def open_data_dir(self):
        try:
            d = app_dir()
            if sys.platform == "win32":
                os.startfile(d)
            return f"已打开程序目录：{d}"
        except Exception as e:
            return f"打开失败：{e}"

    def get_curl(self, rec_id):
        r = self.sniffer.get_detail(int(rec_id))
        if not r:
            return ""
        parts = [f"curl -X {r['method']} '{r['url']}'"]
        for k, v in (r.get("req_headers") or {}).items():
            parts.append(f"  -H '{k}: {v}'")
        if r.get("req_body"):
            body = r["req_body"].replace("'", "'\\''")
            parts.append(f"  -d '{body}'")
        return " \\\n".join(parts)

    def copy_to_clipboard(self, text):
        ok, msg = set_clipboard(text)
        if not ok:
            boot_log("剪贴板失败: " + msg)
        return ok

    def read_clipboard(self):
        return get_clipboard()

    def get_diag(self):
        return self.sniffer.get_diag()

    def rules_path(self):
        """规则配置文件路径，供界面显示/打开"""
        return rules_mod.default_rules_file()

    def open_rules_dir(self):
        try:
            path = rules_mod.default_rules_file()
            if not os.path.exists(path):
                rules_mod.save_rules(self.sniffer.get_rules())
            if sys.platform == "win32":
                os.startfile(os.path.dirname(path))
            return f"已打开规则文件夹：{os.path.dirname(path)}"
        except Exception as e:
            return f"打开失败：{e}"

    def save_body(self, rec_id):
        r = self.sniffer.get_detail(int(rec_id))
        if not r:
            return "记录不存在"
        body = r.get("resp_body") or r.get("req_body") or ""
        if not body:
            return "无正文可保存"
        ext = ".json" if "json" in (r.get("mime") or "") else ".txt"
        safe = "".join(c for c in (r.get("path", "body").split("/")[-1] or "body") if c not in '\\/:*?"<>|')[:40]
        path = os.path.join(app_dir(), f"正文_{r['id']}_{safe}{ext}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            return f"已保存：{path}"
        except Exception as e:
            return f"保存失败：{e}"

    def export_data(self, ids, fmt="xlsx"):
        try:
            all_rows = self.sniffer.get_records()
            idset = set(int(x) for x in ids) if ids else None
            rows = [r for r in all_rows if (idset is None or r["id"] in idset)]
            if not rows:
                return "没有可导出的数据"
            ext = fmt if fmt in ("csv", "json", "har", "xlsx") else "xlsx"
            path = os.path.join(app_dir(), f"抓包数据_{datetime.now():%m%d_%H%M%S}.{ext}")
            do_export(rows, ext, path)
            return f"已导出 {len(rows)} 条 → {path}"
        except Exception as e:
            return f"导出失败：{e}"

    # ---------- 规则引擎 ----------
    def get_rules(self):
        return self.sniffer.get_rules()

    def save_rules(self, rules):
        return self.sniffer.set_rules(rules)

    def get_generated(self, since_id=0):
        try:
            return self.sniffer.get_generated(int(since_id))
        except Exception:
            return []

    def clear_generated(self):
        return self.sniffer.clear_generated()

    def reprocess(self):
        return self.sniffer.reprocess()

    def export_generated(self, ids, fmt="txt"):
        try:
            all_rows = self.sniffer.get_generated()
            idset = set(int(x) for x in ids) if ids else None
            rows = [r for r in all_rows if (idset is None or r["id"] in idset)]
            if not rows:
                return "没有可导出的生成结果"
            ext = fmt if fmt in ("txt", "csv", "json", "xlsx") else "txt"
            path = os.path.join(app_dir(), f"生成地址_{datetime.now():%m%d_%H%M%S}.{ext}")
            export_generated(rows, ext, path)
            return f"已导出 {len(rows)} 条 → {path}"
        except Exception as e:
            return f"导出失败：{e}"

    # ---------- 预设网址书签 ----------
    def get_bookmarks(self):
        bm = _json_file("bookmarks.json", DEFAULT_BOOKMARKS)
        # 首次运行落盘，方便用户直接改文件
        if not os.path.exists(os.path.join(app_dir(), "bookmarks.json")):
            _save_json_file("bookmarks.json", bm)
        return bm

    def save_bookmarks(self, bookmarks):
        if not isinstance(bookmarks, list):
            return "网址格式错误"
        # 只保留 标题 + 网址 两个字段，避免历史配置里混入无关内容
        clean = []
        for b in bookmarks:
            if not isinstance(b, dict):
                continue
            url = str(b.get("url") or "").strip()
            if not url:
                continue
            if not url.startswith(("http://", "https://", "file://")):
                url = "https://" + url
            clean.append({"name": str(b.get("name") or "").strip() or url, "url": url})
        ok = _save_json_file("bookmarks.json", clean)
        return f"已保存 {len(clean)} 个预设网址" if ok else "保存失败（检查程序目录权限）"

    # ---------- 工具导航 ----------
    def get_nav_tools(self):
        tools = _json_file("navtools.json", NAV_TOOLS)
        # 首次运行落盘，方便用户直接改文件
        if not os.path.exists(os.path.join(app_dir(), "navtools.json")):
            _save_json_file("navtools.json", tools)
        return tools

    def save_nav_tools(self, tools):
        if not isinstance(tools, list):
            return "工具导航格式错误"
        ok = _save_json_file("navtools.json", tools)
        return f"已保存 {len(tools)} 个工具" if ok else "保存失败（检查程序目录权限）"

    def reset_nav_tools(self):
        default = json.loads(json.dumps(NAV_TOOLS))
        ok = _save_json_file("navtools.json", default)
        return f"已恢复 {len(default)} 个推荐工具" if ok else "恢复失败（检查程序目录权限）"

    # ---------- 外部程序联动 ----------
    def get_tools(self):
        return _json_file("tools.json", DEFAULT_TOOLS)

    def save_tools(self, tools):
        if not isinstance(tools, list):
            return "工具格式错误"
        ok = _save_json_file("tools.json", tools)
        return f"已保存 {len(tools)} 个外部工具" if ok else "保存失败（检查程序目录权限）"

    def run_tool(self, tool_cmd, text, ext=".txt"):
        """把文本存为临时文件，再按命令模板启动外部程序。{file} 占位符替换为临时文件路径。"""
        try:
            text = str(text if text is not None else "")
            suffix = ext if str(ext).startswith(".") else "." + str(ext)
            fd, path = tempfile.mkstemp(prefix="pudiu_", suffix=suffix)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            template = str(tool_cmd or "").strip()
            if not template:
                return "未配置外部程序命令"
            cmd = template.replace("{file}", path).replace("{text}", text[:500])
            try:
                subprocess.Popen(cmd, shell=True, cwd=app_dir())
            except Exception as e:
                return f"启动外部程序失败：{e}"
            return f"已把 {len(text)} 字写入 {path} 并启动外部程序"
        except Exception as e:
            return f"外部联动失败：{e}"

    def open_in_browser(self, url):
        """用系统默认浏览器打开地址（不经过抓包浏览器）。"""
        try:
            url = str(url or "").strip()
            if not url:
                return "地址为空"
            if not url.startswith(("http://", "https://", "file://")):
                url = "https://" + url
            webbrowser.open(url)
            return "已在系统浏览器打开"
        except Exception as e:
            return f"打开失败：{e}"

    def save_text(self, text, ext=".txt"):
        """把文本保存到程序目录，返回完整路径。"""
        try:
            suffix = ext if str(ext).startswith(".") else "." + str(ext)
            path = os.path.join(app_dir(), f"数据处理_{datetime.now():%m%d_%H%M%S}{suffix}")
            with open(path, "w", encoding="utf-8") as f:
                f.write(str(text if text is not None else ""))
            return f"已保存：{path}"
        except Exception as e:
            return f"保存失败：{e}"


def resource_path(rel):
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = APP_DIR
    return os.path.join(base, rel)


def main():
    try:
        boot_log("=== 程序启动 ===")
        if "--selftest" in sys.argv:
            boot_log("自检模式")
            try:
                s = Sniffer(log_cb=lambda m: boot_log("ENG:" + str(m)))
                s.start(headless=True)
                s.goto("https://www.crccep.cn/")
                import time
                time.sleep(6)
                rows = s.get_records()
                api = [r for r in rows if "findNoticesBynotices" in r["url"]]
                with_cookie = [r for r in rows if r.get("req_cookies")]
                ok1, msg1 = set_clipboard("自检剪贴板OK")
                back = get_clipboard()
                boot_log(f"自检结果: 共{len(rows)}条, 接口{len(api)}条, "
                         f"正文{len(api[0]['resp_body']) if api else 0}字, "
                         f"带Cookie{len(with_cookie)}条, "
                         f"剪贴板{'OK' if ok1 and back == '自检剪贴板OK' else 'FAIL:' + msg1}, "
                         f"诊断={s.get_diag()}")
                s.stop()
            except Exception:
                import traceback
                boot_log("自检失败: " + traceback.format_exc())
            return
        api = Api()
        ui = resource_path("ui.html")
        boot_log("ui路径: " + ui + " 存在=" + str(os.path.exists(ui)))
        # 关键：按屏幕工作区计算窗口尺寸和位置，保证整个窗口都在屏幕内
        wx, wy, ww, wh = screenutil.fit_window(1400, 880, margin=20, anchor="left")
        boot_log(f"窗口几何: x={wx} y={wy} w={ww} h={wh} 工作区={screenutil.work_area()}")
        window = webview.create_window(
            f"{APP_NAME} v{VERSION}", ui,
            width=ww, height=wh, x=wx, y=wy,
            min_size=(900, 560),
            js_api=api, background_color="#f4f6f9")
        api.set_window(window)
        boot_log("窗口已创建，启动 webview")
        webview.start()
        boot_log("webview 正常结束")
    except Exception:
        boot_log("异常: " + __import__("traceback").format_exc())
        raise


if __name__ == "__main__":
    main()
