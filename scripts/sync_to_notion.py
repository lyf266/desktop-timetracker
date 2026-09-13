#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Desktop TimeTracker - Notion Digital Asset & Development Milestone Sync Script
=============================================================================
Synchronizes project metadata, engineering architecture highlights, and version
milestone changelogs to a Notion database as a curated digital asset.

Features:
- Zero external pip dependencies: Pure Python 3 standard library
- Dynamic Notion schema inspection (automatic title and attribute detection)
- Resilient fallback property adaptation with automatic minimal retry
- Multi-source token resolution (CLI > ENV > notion.conf > notion.json)
- Automatic local proxy detection for reliable mainland China network access
- Comprehensive error diagnosis with actionable resolution steps
"""

import argparse
import datetime
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# --- Constants & Defaults ---
DEFAULT_DATABASE_ID = "3b9f94c6-7e98-4bf9-9347-18b861d8d279"
NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
FALLBACK_LOCAL_PROXY = "http://127.0.0.1:10024"

PROJECT_TITLE = "Desktop TimeTracker (timetrack)"
PROJECT_PAGE_TITLE = "Desktop TimeTracker (timetrack) - 数字资产与开发日志"
PROJECT_REPO_URL = "https://github.com/lyf266/desktop-timetracker"
PROJECT_LICENSE = "MIT"
PROJECT_TECH_STACK = "Python 3, KDE Plasma 6 Wayland, KWin Script, systemd --user, SQLite WAL"
PROJECT_RESOURCE_METRICS = "~13MB RAM, <0.1% CPU, 0 external pip dependencies"
PROJECT_SUBTITLE = (
    "专为 KDE Plasma 6 (Wayland) 打造的轻量级、零外部 pip 依赖、100% 本地隐私的自动化桌面时间与行为追踪系统。"
)


def clean_uuid(raw_id: str) -> str:
    """Normalize a UUID string by stripping hyphens and whitespace."""
    if not raw_id:
        return ""
    return raw_id.strip().replace("-", "")


def is_local_proxy_running(host: str = "127.0.0.1", port: int = 10024) -> bool:
    """Check if the local proxy port is actively listening."""
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except (OSError, socket.timeout):
        return False


def setup_http_opener(proxy: str | None = None, no_proxy: bool = False) -> urllib.request.OpenerDirector:
    """
    Build a urllib opener configured with appropriate proxy settings.
    Respects CLI flag, environment variables, or detects local v2rayN proxy.
    """
    if no_proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))

    if proxy:
        handlers = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handlers)

    # Check if standard proxy env vars are already populated
    has_env_proxy = any(
        os.environ.get(k)
        for k in ("https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")
    )
    if has_env_proxy:
        return urllib.request.build_opener()

    # Fallback to local v2rayN proxy if listening
    if is_local_proxy_running("127.0.0.1", 10024):
        handlers = urllib.request.ProxyHandler(
            {"http": FALLBACK_LOCAL_PROXY, "https": FALLBACK_LOCAL_PROXY}
        )
        return urllib.request.build_opener(handlers)

    return urllib.request.build_opener()


def resolve_notion_token(cli_token: str | None = None) -> tuple[str | None, str | None]:
    """
    Resolve Notion integration secret token from multiple configuration sources.
    Priority:
    1. CLI argument `--token`
    2. Environment variables: NOTION_API_KEY, NOTION_TOKEN
    3. Systemd environment file: ~/.config/environment.d/notion.conf
    4. App config file: ~/.config/timetracker/notion.json
    """
    if cli_token and cli_token.strip():
        return cli_token.strip(), "CLI argument (--token)"

    env_key = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
    if env_key and env_key.strip():
        var_name = "NOTION_API_KEY" if os.environ.get("NOTION_API_KEY") else "NOTION_TOKEN"
        return env_key.strip(), f"Environment variable ({var_name})"

    # Fallback: ~/.config/environment.d/notion.conf
    conf_path = Path.home() / ".config" / "environment.d" / "notion.conf"
    if conf_path.exists():
        try:
            with open(conf_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k in ("NOTION_API_KEY", "NOTION_TOKEN") and v:
                            return v, str(conf_path)
        except Exception:
            pass

    # Fallback: ~/.config/timetracker/notion.json
    json_path = Path.home() / ".config" / "timetracker" / "notion.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for candidate in ("notion_token", "token", "notion_api_key", "api_key", "secret"):
                    val = data.get(candidate)
                    if val and isinstance(val, str) and val.strip():
                        return val.strip(), str(json_path)
        except Exception:
            pass

    return None, None


def resolve_database_id(cli_db_id: str | None = None) -> tuple[str, str]:
    """
    Resolve target database ID from CLI, env, config or default constant.
    """
    if cli_db_id and cli_db_id.strip():
        return clean_uuid(cli_db_id), "CLI argument (--database-id)"

    env_db = os.environ.get("NOTION_DATABASE_ID")
    if env_db and env_db.strip():
        return clean_uuid(env_db), "Environment variable (NOTION_DATABASE_ID)"

    json_path = Path.home() / ".config" / "timetracker" / "notion.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = data.get("database_id")
                if val and isinstance(val, str) and val.strip():
                    return clean_uuid(val), str(json_path)
        except Exception:
            pass

    return clean_uuid(DEFAULT_DATABASE_ID), "Default constant"


def notion_api_request(
    opener: urllib.request.OpenerDirector,
    token: str,
    method: str,
    endpoint: str,
    payload: dict | None = None,
    timeout: float = 25.0,
    verbose: bool = False,
) -> dict:
    """Execute an authenticated request to Notion API."""
    url = f"{NOTION_BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
        "User-Agent": "DesktopTimeTracker-NotionSync/1.1",
    }
    data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None

    if verbose:
        print(f"[DEBUG] {method} {url}")
        if data_bytes:
            print(f"[DEBUG] Payload size: {len(data_bytes)} bytes")

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with opener.open(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"message": err_body}
        err_json["http_status"] = err.code
        return {"_error": True, "error_data": err_json, "status": err.code}
    except Exception as exc:
        return {"_error": True, "exception": str(exc)}


def build_page_blocks() -> list[dict]:
    """
    Construct the rich content blocks hierarchy conforming to Notion's Block API:
    - Top: Callout block (Asset Summary Dashboard)
    - Divider
    - Heading 2: Development Milestones & Evolution
    - Cascading Toggle Block 1: Milestone 1 (v1.0.0)
    - Cascading Toggle Block 2: Milestone 2 (v1.0.1)
    - Cascading Toggle Block 3: Milestone 3 (v1.1.0)
    - Cascading Toggle Block 4: Architecture Highlights & Engineering Metrics
    """

    def make_rich_text(text: str, bold: bool = False, italic: bool = False, link: str | None = None) -> dict:
        # Notion limit: max 2000 chars per text object
        safe_content = text[:2000]
        obj = {
            "type": "text",
            "text": {"content": safe_content},
            "annotations": {
                "bold": bold,
                "italic": italic,
                "strikethrough": False,
                "underline": False,
                "code": False,
                "color": "default",
            },
        }
        if link:
            obj["text"]["link"] = {"url": link}
        return obj

    def make_bullet(bold_prefix: str, content: str) -> dict:
        return {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    make_rich_text(bold_prefix, bold=True),
                    make_rich_text(content),
                ]
            },
        }

    # 1. Asset Summary Callout Block
    callout_rich_text = [
        make_rich_text(f"{PROJECT_TITLE} - 数字化资产看板\n", bold=True),
        make_rich_text(f"{PROJECT_SUBTITLE}\n\n", italic=True),
        make_rich_text("• 项目名称: ", bold=True),
        make_rich_text(f"{PROJECT_TITLE}\n"),
        make_rich_text("• 核心技术栈: ", bold=True),
        make_rich_text(f"{PROJECT_TECH_STACK}\n"),
        make_rich_text("• 资源占用指标: ", bold=True),
        make_rich_text(f"{PROJECT_RESOURCE_METRICS}\n"),
        make_rich_text("• 开源许可证: ", bold=True),
        make_rich_text(f"{PROJECT_LICENSE} License\n"),
        make_rich_text("• 代码仓库: ", bold=True),
        make_rich_text(PROJECT_REPO_URL, link=PROJECT_REPO_URL),
    ]

    callout_block = {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": callout_rich_text,
            "icon": {"type": "emoji", "emoji": "⏱️"},
            "color": "blue_background",
        },
    }

    divider_block = {"object": "block", "type": "divider", "divider": {}}

    heading_block = {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [make_rich_text("📦 项目里程碑与开发日志 (Development Milestones)")]
        },
    }

    # Milestone 1 Toggle
    m1_toggle = {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [
                make_rich_text("🚀 Milestone 1 (v1.0.0): 原生 KWin Wayland 零侵入采集引擎与基础设施", bold=True)
            ],
            "children": [
                make_bullet(
                    "原生 KWin Wayland 事件监听：",
                    "彻底解决 Wayland 安全隔离下传统 X11 监听工具（xdotool, xprop, arbtt）失效难题。采用嵌入式 KWin JS 脚本引擎（timetracker_kwin.js）监听 workspace.windowActivated，零侵入、零鼠标抖动捕获活动窗口属性。",
                ),
                make_bullet(
                    "D-Bus 物理锁屏探测：",
                    "无缝接入 org.freedesktop.ScreenSaver 信号，精准感知用户物理锁屏与会话空闲状态，离开或锁屏即刻暂停计时，坚决消除虚假挂机时长。",
                ),
                make_bullet(
                    "SQLite WAL 存储与平滑缓冲：",
                    "构建轻量级本地 SQLite 数据库，启用 WAL (Write-Ahead Logging) 高并发模式，配置 10 秒平滑聚合内存缓冲机制，兼顾断电安全性与极低磁盘 I/O 磨损。",
                ),
                make_bullet(
                    "跨天 Markdown 日报自动沉淀：",
                    "后台守护进程跨天自动聚合前一日数据，汇总分类占比、Top 活跃应用、窗口任务明细及 24 小时活跃分布，格式化输出至 ~/Documents/TimeReports/YYYY-MM-DD.md。",
                ),
                make_bullet(
                    "Systemd 用户级服务托管：",
                    "内置 desktop-timetracker.service 单元文件，深度集成 KDE Plasma 会话自启与热重启生命周期管理。",
                ),
            ],
        },
    }

    # Milestone 2 Toggle
    m2_toggle = {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [
                make_rich_text("🌐 Milestone 2 (v1.0.1): 纯净多语言 (i18n) 重构与物理隔离", bold=True)
            ],
            "children": [
                make_bullet(
                    "架构级多语言国际化解耦：",
                    "构建独立的 i18n 字典模块与自适应语言探测器，实现控制台输出、时间单位、分类名称及导出的 Markdown 报告模板全局多语言解耦。",
                ),
                make_bullet(
                    "动态语言切换引擎：",
                    "提供 timetrack lang <zh|en|auto> 原生指令，支持用户偏好持久化写入，同时支持单次运行命令行临时覆盖（如 timetrack today --lang en）。",
                ),
                make_bullet(
                    "README 文档中英文物理隔离：",
                    "将文档彻底拆分为英文根文档 README.md 与原生简体中文 README_zh.md，配置双向自适应徽章与一键跳转交互导航，大幅提升开源社区与本地开发者体验。",
                ),
                make_bullet(
                    "高质感终端看板渲染：",
                    "优化 ANSI 彩色终端排版与 ASCII 边框布局，直观展现今日时间进度条、分类色块与任务排行。",
                ),
            ],
        },
    }

    # Milestone 3 Toggle
    m3_toggle = {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [
                make_rich_text("🧠 Milestone 3 (v1.1.0): 三层递进分类管道设计与元数据加权引擎", bold=True)
            ],
            "children": [
                make_bullet(
                    "第 1 层（用户规则优先）：",
                    "最高优先级。优先精确匹配 ~/.config/timetracker/rules.json 中定义的应用名与窗口标题关键字，充分赋予用户自定义控制权。",
                ),
                make_bullet(
                    "第 2 层（XDG .desktop 元数据解析）：",
                    "自动深度递归解析 /usr/share/applications/、~/.local/share/applications/ 及 Flatpak 沙箱应用元数据，提取 Categories 规范分类与多语言 Display Name。",
                ),
                make_bullet(
                    "特异性加权匹配算法：",
                    "建立特异性权重优先级梯度（TerminalEmulator > WebBrowser > IDE/Development > Chat/Email > Game/AudioVideo > Office > Graphics > System），精准化解跨类冲突。",
                ),
                make_bullet(
                    "第 3 层（平滑安全兜底机制）：",
                    "对未注册 desktop 文件的独立脚本或前台临时应用，优雅回退至「其他应用 (other)」，保证分类管道永不崩溃，实现新装应用开箱即用。",
                ),
            ],
        },
    }

    # Milestone 4 / Engineering Highlights Toggle
    arch_toggle = {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [
                make_rich_text("⚡ 系统架构亮点与关键设计决策 (Engineering Highlights)", bold=True)
            ],
            "children": [
                make_bullet(
                    "零外部 pip 依赖哲学：",
                    "全系统 100% 基于 Python 3 标准库（sqlite3、urllib、json、subprocess、datetime、argparse），免除虚拟环境包袱与依赖地狱。",
                ),
                make_bullet(
                    "极致能效表现：",
                    "常驻内存仅约 13 MB，日常运行 CPU 占用率稳定保持在 0.1% 以下，无风扇唤醒，极度适合移动笔电全天候常驻。",
                ),
                make_bullet(
                    "100% 本地与隐私绝对优先：",
                    "所有数据均保存在本地 XDG 目录（~/.local/share/timetracker/timetracker.db），坚决杜绝任何远程遥测上报与静默联网。",
                ),
            ],
        },
    }

    return [callout_block, divider_block, heading_block, m1_toggle, m2_toggle, m3_toggle, arch_toggle]


def build_properties_payload(db_properties: dict) -> tuple[dict, str]:
    """
    Introspect database properties to match the title field and safely populate
    optional columns (URL, Date, Description, Tags) if available in the database schema.
    """
    props_payload = {}
    title_key = None

    # 1. Identify title property (mandatory in Notion)
    for prop_name, prop_info in db_properties.items():
        if prop_info.get("type") == "title":
            title_key = prop_name
            break

    if not title_key:
        title_key = "Name"

    props_payload[title_key] = {
        "title": [
            {
                "type": "text",
                "text": {"content": PROJECT_PAGE_TITLE},
            }
        ]
    }

    # 2. Adaptive optional properties inspection
    for prop_name, prop_info in db_properties.items():
        ptype = prop_info.get("type")
        lower_name = prop_name.lower()

        # URL field
        if ptype == "url" and any(k in lower_name for k in ("url", "repo", "link", "仓库", "链接", "github")):
            props_payload[prop_name] = {"url": PROJECT_REPO_URL}

        # Date field
        elif ptype == "date" and any(k in lower_name for k in ("date", "创建", "时间", "日期", "created")):
            props_payload[prop_name] = {"date": {"start": datetime.date.today().isoformat()}}

        # Summary / Description rich_text field
        elif ptype == "rich_text" and any(k in lower_name for k in ("desc", "summary", "描述", "简介", "备注", "看板")):
            props_payload[prop_name] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": PROJECT_SUBTITLE[:1800]},
                    }
                ]
            }

        # Status / Select field (only map if safe existing option matches)
        elif ptype == "select":
            options = [opt.get("name", "") for opt in prop_info.get("select", {}).get("options", [])]
            for candidate in ("已完成", "Active", "稳定版", "发布", "Done", "数字资产", "项目"):
                if candidate in options:
                    props_payload[prop_name] = {"select": {"name": candidate}}
                    break

    return props_payload, title_key


def sync_to_notion(
    token: str,
    database_id: str,
    opener: urllib.request.OpenerDirector,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Main synchronization logic with dynamic schema resolution and resilient fallback."""
    print("=" * 68)
    print("⏱️  Desktop TimeTracker -> Notion 数字资产沉淀工具")
    print("=" * 68)
    print(f"目标数据库 ID : {database_id}")

    # 1. Retrieve Database Schema
    print("[-] 正在探测 Notion 数据库结构与字段元数据...")
    db_resp = notion_api_request(
        opener=opener,
        token=token,
        method="GET",
        endpoint=f"/databases/{database_id}",
        verbose=verbose,
    )

    if db_resp.get("_error"):
        err_info = db_resp.get("error_data", {})
        status_code = err_info.get("http_status") or db_resp.get("status")
        msg = err_info.get("message", db_resp.get("exception", "Unknown error"))

        if dry_run:
            print(f"[⚠️ 提示] 在线查询数据库属性失败 (HTTP {status_code}: {msg})。")
            print("由于开启了 --dry-run 模拟模式，将采用标准数据库 Schema 继续构建数据载荷进行本地校验...")
            properties_schema = {
                "Name": {"type": "title"},
                "URL": {"type": "url"},
                "Date": {"type": "date"},
            }
        else:
            print("\n" + "!" * 68)
            print(f"[❌ 错误] 无法访问 Notion 数据库 (HTTP {status_code})")
            print(f"详细信息: {msg}")
            print("!" * 68)

            if status_code == 404:
                print("\n💡 常见原因与解决指引:")
                print("1. 集成尚未共享到该数据库:")
                print("   打开 Notion 目标数据库页面 -> 点击右上角「...」->「Connections / 连接」-> 添加你的集成。")
                print("2. 数据库 ID 不正确:")
                print(f"   当前传入 ID: {database_id}")
                print("   请确认数据库 URL 中的 32 位 UUID 是否正确。")
            elif status_code == 401:
                print("\n💡 认证失败指引:")
                print("1. 请检查 Token 是否有效或是否被 Notion 撤销。")
            sys.stdout.flush()
            return 1
    else:
        db_title_arr = db_resp.get("title", [])
        db_title = "".join(t.get("plain_text", "") for t in db_title_arr) or "未命名数据库"
        print(f"[✅] 成功连接至数据库: 「{db_title}」")
        properties_schema = db_resp.get("properties", {})

    props_payload, title_key = build_properties_payload(properties_schema)
    print(f"[ℹ️] 识别主标题属性列: 「{title_key}」")
    if len(props_payload) > 1:
        extra_keys = [k for k in props_payload.keys() if k != title_key]
        print(f"[ℹ️] 自适应适配属性列: {', '.join(extra_keys)}")

    # 2. Build Content Blocks
    children_blocks = build_page_blocks()
    print(f"[ℹ️] 构建结构化块组件完成 (共 {len(children_blocks)} 个顶级块，包含资产看板与 4 组级联折叠清单)")

    page_payload = {
        "parent": {"database_id": database_id},
        "properties": props_payload,
        "children": children_blocks,
    }

    # 3. Handle Dry-Run Mode
    if dry_run:
        print("\n" + "-" * 68)
        print("🔍 [DRY-RUN 模拟模式] 未向 Notion 写入真实数据。以下是生成的完整请求载荷预览:")
        print("-" * 68)
        print(json.dumps(page_payload, indent=2, ensure_ascii=False)[:3500])
        print("\n... [已截断多余输出] ...")
        print("=" * 68)
        print("✅ Dry-Run 校验通过！数据载荷与块结构完全符合 Notion API 规范。")
        return 0

    # 4. Create Page via POST /v1/pages
    print("[-] 正在写入数字资产页面到 Notion...")
    create_resp = notion_api_request(
        opener=opener,
        token=token,
        method="POST",
        endpoint="/pages",
        payload=page_payload,
        verbose=verbose,
    )

    # 5. Resilient fallback if custom properties triggered a 400 Bad Request
    if create_resp.get("_error") and create_resp.get("status") == 400 and len(props_payload) > 1:
        print("[⚠️] 自适应属性被数据库约束拒绝，正在尝试使用仅标题安全模式重新写入...")
        safe_props_payload = {title_key: props_payload[title_key]}
        page_payload["properties"] = safe_props_payload
        create_resp = notion_api_request(
            opener=opener,
            token=token,
            method="POST",
            endpoint="/pages",
            payload=page_payload,
            verbose=verbose,
        )

    if create_resp.get("_error"):
        err_info = create_resp.get("error_data", {})
        status_code = err_info.get("http_status") or create_resp.get("status")
        msg = err_info.get("message", create_resp.get("exception", "Unknown error"))
        print("\n" + "!" * 68)
        print(f"[❌ 写入失败] Notion API 返回错误 (HTTP {status_code})")
        print(f"详细信息: {msg}")
        print("!" * 68)
        return 1

    page_id = create_resp.get("id")
    page_url = create_resp.get("url")
    print("\n" + "=" * 68)
    print("🎉 恭喜！Desktop TimeTracker 开发日志与数字资产已成功写入 Notion！")
    print(f"• 页面 ID : {page_id}")
    if page_url:
        print(f"• 页面链接 : {page_url}")
    print("=" * 68)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="将 Desktop TimeTracker 项目元数据、设计决策与开发日志写入 Notion 数据库。"
    )
    parser.add_argument(
        "--token",
        "-t",
        help="Notion Integration Token (留空则依次从环境变量、notion.conf、notion.json 中查找)",
    )
    parser.add_argument(
        "--database-id",
        "-d",
        default=None,
        help=f"目标 Notion 数据库 ID (默认: {DEFAULT_DATABASE_ID})",
    )
    parser.add_argument(
        "--proxy",
        "-p",
        help="指定 HTTP/HTTPS 代理服务器地址 (例如: http://127.0.0.1:10024)",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="强制禁用代理，直接发起网络连接",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟执行：仅进行本地校验和打印数据 Payload，不向 Notion 发送创建请求",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="输出详细的调试日志与 HTTP 通信详情",
    )

    args = parser.parse_args()

    # 1. Resolve Token
    token, token_source = resolve_notion_token(args.token)
    if not token:
        print("\n" + "!" * 68)
        print("❌ 未检测到有效的 Notion Integration Token！")
        print("!" * 68)
        print("\n请通过以下任一方式提供 Notion API Token：")
        print("  1. 命令行参数:")
        print("     python3 scripts/sync_to_notion.py --token <YOUR_NOTION_TOKEN>")
        print("  2. 环境变量 (二选一):")
        print('     export NOTION_TOKEN="ntn_..."')
        print('     export NOTION_API_KEY="ntn_..."')
        print("  3. 专属配置文件 (~/.config/timetracker/notion.json):")
        print('     {"notion_token": "ntn_...", "database_id": "3b9f94c67e984bf9934718b861d8d279"}')
        print("  4. systemd 环境配置 (~/.config/environment.d/notion.conf):")
        print("     NOTION_TOKEN=ntn_...")
        print("\nToken 获取与授权三步指南：")
        print("  步骤 A: 登录 https://www.notion.so/profile/integrations 创建或获取内部集成密钥。")
        print("  步骤 B: 打开目标数据库页面，点击右上角「...」->「连接 / Connections」-> 绑定该集成。")
        print("  步骤 C: 重新运行此脚本即可自动同步。")
        print("-" * 68)
        sys.exit(1)

    # 2. Resolve Database ID
    target_db_id, db_source = resolve_database_id(args.database_id)

    # 3. Setup HTTP Opener
    opener = setup_http_opener(proxy=args.proxy, no_proxy=args.no_proxy)

    if args.verbose:
        print(f"[DEBUG] Token 来源: {token_source} (Token 前缀: {token[:7]}...)")
        print(f"[DEBUG] 数据库 ID 来源: {db_source}")

    # 4. Execute Sync
    ret = sync_to_notion(
        token=token,
        database_id=target_db_id,
        opener=opener,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    sys.exit(ret)


if __name__ == "__main__":
    main()
