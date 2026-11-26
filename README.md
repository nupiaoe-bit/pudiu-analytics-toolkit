# Pudiu 大数据分析可视化工具

基于 Chrome DevTools Protocol 的**本地被动抓包 + 数据分析**桌面工具。你在浏览器里正常访问网站、登录、翻页，工具实时捕获请求与响应，按规则从响应字段生成地址并自动累积、去重、导出。所有数据只在本机处理，不上传任何服务器。

更多工具：[pudiu toolbx](https://tool.pudiu.com/)  [资源猎手](http://hunter.pudiu.com)  [ip在线查询工具](https://ip.pudiu.com)  [数据清洗工具
](https://url.pudiu.com)   [pudiu shop](https://www.pudiu.com/)
完整用法见 [使用说明.md](使用说明.md)。

## 主要功能

- **被动抓包**：CDP `Network` 域监听，可自行启动 Chrome，也可附加已用调试模式打开的 Chrome（默认端口 9222）
- **请求详情**：响应头、响应正文、请求头、Cookie；正文支持鼠标选中复制、点击编辑、全屏查看、JSON 高亮与搜索
- **规则提取**：配置接口关键字 + JSON 字段名 + 前后缀，翻页时自动累积生成地址并去重
- **结果处理**：分页、筛选、批量复制、编辑、系统浏览器/抓包浏览器一键打开、TXT / Excel / CSV / JSON 导出
- **工具导航**：19 个推荐的数据分析与可视化在线工具，分类浏览、搜索、查看详情、一键打开，支持自定义
- **内置工具箱**：JSON 格式化/列字段/按字段提取、正则、批量前后缀、去重排序、网址提取、Base64、统计等
- **外部程序联动**：配置命令模板（`{file}` / `{text}` 占位符）调用本机 exe/脚本
- **预设网址**：顶部书签条，默认 `tool.pudiu.com` 与 `bing.com`，可自行增删

## 快速开始

1. 双击 `免安装版/以调试模式启动Chrome.bat` 启动带调试端口的 Chrome（也可在软件里点「开始抓包」自行启动）
2. 运行 `Pudiu大数据分析可视化工具.exe`，点「开始抓包」或「附加已开浏览器」
3. 在 Chrome 里正常访问目标网站，请求会实时出现在「抓包」页
4. 点请求地址查看响应；在「规则」页配置字段提取；翻页后到「结果」页复制或导出

> 普通双击打开的 Chrome 没有调试端口，外部程序读不到明文数据，必须通过上述 bat 启动调试版 Chrome。

## 源码结构

| 文件 | 作用 |
|---|---|
| `main.py` | 程序入口、pywebview 后端 API、书签/工具导航/外部联动配置 |
| `sniffer.py` | Playwright + CDP 抓包引擎、命令队列、正文补取、规则应用 |
| `rules.py` | 规则持久化与 JSON 字段递归提取 |
| `exporter.py` | 抓包记录与生成结果的 CSV / XLSX / JSON / HAR 导出 |
| `cliputil.py` | Windows 原生剪贴板（`CF_UNICODETEXT`） |
| `screenutil.py` | 屏幕工作区计算、DPI 感知、窗口与 Chrome 起始位置 |
| `ui.html` | 全部界面与前端交互（总览/抓包/规则/结果/工具/导航/设置） |
| `使用说明.md` | 完整使用文档 |
| `Pudiu大数据分析可视化工具.spec` | PyInstaller 打包配置（含 Playwright driver） |
| `app.ico` / `app.png` | 应用图标 |
| `免安装版/以调试模式启动Chrome.bat` | 屏幕自适应的调试 Chrome 启动脚本 |

## 从源码运行 / 打包

依赖：Python 3.13、`pywebview`、`playwright`、`PyInstaller`、`Pillow`（仅生成图标时需要）。

```bash
python main.py                                  # 直接运行源码
python -m PyInstaller Pudiu大数据分析可视化工具.spec   # 打包单文件 exe
```

打包产物在 `dist/`，复制到 `免安装版/` 即可。

## 运行时配置

程序首次运行会在 exe 同目录生成 `rules.json`、`bookmarks.json`、`navtools.json`、`tools.json`，这些是个人配置，不纳入版本库，可直接编辑或在界面里管理。

## 许可

仅供个人学习与内部数据处理使用。
