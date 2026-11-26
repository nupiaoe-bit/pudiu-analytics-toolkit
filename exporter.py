# -*- coding: utf-8 -*-
"""抓包数据导出：CSV / Excel / JSON / HAR"""
import csv
import json
import os
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape


def _safe(s):
    return "" if s is None else str(s)


def export_csv(rows, path):
    cols = ["id", "time", "method", "status", "host", "path", "type", "mime",
            "size", "duration", "url", "req_body", "resp_body"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _safe(r.get(c, "")) for c in cols})


def export_json(rows, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def export_har(rows, path):
    """导出为 HAR 1.2 格式，可导入 Fiddler/Charles/Chrome"""
    entries = []
    for r in rows:
        req_headers = [{"name": k, "value": _safe(v)} for k, v in (r.get("req_headers") or {}).items()]
        resp_headers = [{"name": k, "value": _safe(v)} for k, v in (r.get("resp_headers") or {}).items()]
        post = r.get("req_body") or ""
        entry = {
            "startedDateTime": datetime.now().isoformat(),
            "time": r.get("duration", 0),
            "request": {
                "method": r.get("method", "GET"),
                "url": r.get("url", ""),
                "httpVersion": "HTTP/1.1",
                "headers": req_headers,
                "queryString": [],
                "cookies": [],
                "headersSize": -1,
                "bodySize": len(post),
                "postData": ({"mimeType": r.get("mime", ""), "text": post} if post else None),
            },
            "response": {
                "status": r.get("status", 0),
                "statusText": "",
                "httpVersion": "HTTP/1.1",
                "headers": resp_headers,
                "cookies": [],
                "content": {"size": r.get("size", 0), "mimeType": r.get("mime", ""), "text": r.get("resp_body", "")},
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": r.get("size", 0),
            },
            "cache": {},
            "timings": {"send": 0, "wait": r.get("duration", 0), "receive": 0},
        }
        entries.append(entry)
    har = {"log": {"version": "1.2", "creator": {"name": "Pudiu 大数据分析可视化工具", "version": "4.0"},
                   "pages": [], "entries": entries}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(har, f, ensure_ascii=False, indent=2)


def export_xlsx(rows, path):
    """零依赖生成 xlsx（内联字符串）"""
    cols = [
        ("序号", "id"), ("时间", "time"), ("方法", "method"), ("状态码", "status"),
        ("域名", "host"), ("路径", "path"), ("类型", "type"), ("MIME", "mime"),
        ("大小(B)", "size"), ("耗时(ms)", "duration"), ("完整URL", "url"),
        ("请求体", "req_body"), ("响应体", "resp_body"),
    ]

    def col_letter(i):
        s = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

    def sheet_xml(data):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
               '<cols>']
        for i in range(len(cols)):
            w = 40 if cols[i][1] in ("url", "resp_body", "req_body") else 16
            out.append(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>')
        out.append('</cols><sheetData>')
        # 表头
        out.append('<row r="1">')
        for i, (title, _) in enumerate(cols):
            out.append(f'<c r="{col_letter(i)}1" t="inlineStr"><is><t>{xml_escape(title)}</t></is></c>')
        out.append('</row>')
        for ri, row in enumerate(data, start=2):
            out.append(f'<row r="{ri}">')
            for i, (_, key) in enumerate(cols):
                val = _safe(row.get(key, ""))[:32000]
                if key in ("id", "status", "size", "duration"):
                    try:
                        out.append(f'<c r="{col_letter(i)}{ri}"><v>{float(val) if val else 0}</v></c>')
                        continue
                    except Exception:
                        pass
                out.append(f'<c r="{col_letter(i)}{ri}" t="inlineStr"><is><t xml:space="preserve">{xml_escape(val)}</t></is></c>')
            out.append('</row>')
        out.append('</sheetData></worksheet>')
        return "".join(out)

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="抓包记录" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    wb_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml(rows))


def export_generated(rows, fmt, path):
    """导出生成结果地址列表（纯文本/TXT：一行一个，方便直接复制粘贴）"""
    if fmt == "txt":
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write((r.get("output") or "") + "\n")
    elif fmt == "csv":
        cols = ["id", "time", "rule", "key", "value", "output", "source_url"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: _safe(r.get(c, "")) for c in cols})
    elif fmt == "json":
        export_json(rows, path)
    else:
        # Excel：用通用 xlsx 结构但换列名
        export_xlsx_generic(rows, path, [
            ("序号", "id"), ("时间", "time"), ("规则", "rule"),
            ("字段名", "key"), ("原始值", "value"), ("生成地址", "output"),
            ("来源接口", "source_url"),
        ])


def export_xlsx_generic(rows, path, cols):
    def col_letter(i):
        s = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

    def sheet_xml(data):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
               '<cols>']
        for i in range(len(cols)):
            w = 45 if cols[i][1] in ("url", "output", "source_url") else 18
            out.append(f'<col min="{i+1}" max="{i+1}" width="{w}" customWidth="1"/>')
        out.append('</cols><sheetData><row r="1">')
        for i, (title, _) in enumerate(cols):
            out.append(f'<c r="{col_letter(i)}1" t="inlineStr"><is><t>{xml_escape(title)}</t></is></c>')
        out.append('</row>')
        for ri, row in enumerate(data, start=2):
            out.append(f'<row r="{ri}">')
            for i, (_, key) in enumerate(cols):
                val = _safe(row.get(key, ""))[:32000]
                if key == "id":
                    out.append(f'<c r="{col_letter(i)}{ri}"><v>{val or 0}</v></c>')
                else:
                    out.append(f'<c r="{col_letter(i)}{ri}" t="inlineStr"><is><t xml:space="preserve">{xml_escape(val)}</t></is></c>')
            out.append('</row>')
        out.append('</sheetData></worksheet>')
        return "".join(out)

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    workbook = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="生成结果" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    wb_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml(rows))


def do_export(rows, fmt, path):
    if fmt == "csv":
        export_csv(rows, path)
    elif fmt == "json":
        export_json(rows, path)
    elif fmt == "har":
        export_har(rows, path)
    else:
        export_xlsx(rows, path)
