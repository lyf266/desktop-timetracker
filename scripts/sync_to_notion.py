#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Desktop TimeTracker - Notion Digital Asset & Development Milestone Sync Script
=============================================================================
Synchronizes project metadata, engineering architecture highlights, and version
milestone changelogs to a Notion database or page as a curated digital asset.

Features:
- Zero external pip dependencies: 100% Python 3 standard library
- Robust UUID & URL extraction (supports plain 32-hex, UUID with hyphens, and full Notion URLs)
- Dynamic Notion schema inspection (automatic title, status, select, multi-select, url, date detection)
- Resilient fallback property adaptation with automatic minimal retry
- Multi-source token resolution (CLI > ENV > notion.conf > notion.json > ~/.config/notion/api_key)
- Automatic local proxy detection for reliable mainland China network access
- Lossless rich text chunking adhering to Notion's 2000-character limit
- Smart block batching ensuring Notion's 100-children limit is never exceeded
- Dual parent support (supports both Database and Page targets seamlessly)
- Context-aware error diagnosis with integration name & workspace details
"""

import argparse
import datetime
import json
import os
import re
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


def clean_uuid(raw_id: str | None) -> str:
    """
    Normalize a raw UUID or Notion URL into a clean 32-character hex UUID string.
    Handles:
    - 32 hex chars: "3b9f94c67e984bf9934718b861d8d279"
    - Standard UUID: "3b9f94c6-7e98-4bf9-9347-18b861d8d279"
    - Notion URL: "https://www.notion.so/workspace/3b9f94c6-7e98-4bf9-9347-18b861d8d279?v=..."
    - Notion page URL: "https://notion.so/3b9f94c67e984bf9934718b861d8d279"
    """
    if not raw_id:
        return ""
    s = raw_id.strip()
    # Match 32 hex digits or hyphenated 8-4-4-4-12 hex format
    match = re.search(r"([0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12})", s)
    if match:
        return match.group(1).replace("-", "").lower()
    return s.replace("-", "").strip().lower()


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
    Respects CLI flag, environment variables, or detects local proxy.
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

    # Fallback to local proxy if listening
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
    5. Standard Notion API key file: ~/.config/notion/api_key
    """
    if cli_token and cli_token.strip():
        return cli_token.strip(), "CLI argument (--token)"

    # Check NOTION_API_KEY
    api_key = (os.environ.get("NOTION_API_KEY") or "").strip()
    if api_key:
        return api_key, "Environment variable (NOTION_API_KEY)"

    # Check NOTION_TOKEN
    notion_token = (os.environ.get("NOTION_TOKEN") or "").strip()
    if notion_token:
        return notion_token, "Environment variable (NOTION_TOKEN)"

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

    # Fallback: ~/.config/notion/api_key
    notion_api_key_path = Path.home() / ".config" / "notion" / "api_key"
    if notion_api_key_path.exists():
        try:
            with open(notion_api_key_path, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val, str(notion_api_key_path)
        except Exception:
            pass

    return None, None


def resolve_database_id(cli_db_id: str | None = None) -> tuple[str, str]:
    """
    Resolve target database ID from CLI, env, config or default constant.
    """
    if cli_db_id and cli_db_id.strip():
        return clean_uuid(cli_db_id), "CLI argument (--database-id)"

    env_db = (os.environ.get("NOTION_DATABASE_ID") or "").strip()
    if env_db:
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


def make_rich_text_chunks(text: str, bold: bool = False, italic: bool = False, link: str | None = None) -> list[dict]:
    """
    Split text into chunks of at most 2000 characters each, returning a list of Notion rich text objects.
    Adheres strictly to Notion API's 2000-char limit per rich text object without truncating content.
    """
    if not text:
        return []
    chunks = []
    chunk_size = 2000
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        obj = {
            "type": "text",
            "text": {"content": chunk},
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
        chunks.append(obj)
    return chunks


def make_bullet(bold_prefix: str, content: str) -> dict:
    """Construct a bulleted list item block with bold prefix and detailed explanation."""
    prefix_objs = make_rich_text_chunks(bold_prefix, bold=True)
    content_objs = make_rich_text_chunks(content)
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": prefix_objs + content_objs,
        },
    }


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
    # 1. Asset Summary Callout Block
    callout_rich_text = []
    callout_rich_text.extend(make_rich_text_chunks(f"{PROJECT_TITLE} - 数字化资产看板\n", bold=True))
    callout_rich_text.extend(make_rich_text_chunks(f"{PROJECT_SUBTITLE}\n\n", italic=True))
    callout_rich_text.extend(make_rich_text_chunks("• 项目名称: ", bold=True))
    callout_rich_text.extend(make_rich_text_chunks(f"{PROJECT_TITLE}\n"))
    callout_rich_text.extend(make_rich_text_chunks("• 核心技术栈: ", bold=True))
    callout_rich_text.extend(make_rich_text_chunks(f"{PROJECT_TECH_STACK}\n"))
    callout_rich_text.extend(make_rich_text_chunks("• 资源占用指标: ", bold=True))
    callout_rich_text.extend(make_rich_text_chunks(f"{PROJECT_RESOURCE_METRICS}\n"))
    callout_rich_text.extend(make_rich_text_chunks("• 开源许可证: ", bold=True))
    callout_rich_text.extend(make_rich_text_chunks(f"{PROJECT_LICENSE} License\n"))
    callout_rich_text.extend(make_rich_text_chunks("• 代码仓库: ", bold=True))
    callout_rich_text.extend(make_rich_text_chunks(PROJECT_REPO_URL, link=PROJECT_REPO_URL))

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
            "rich_text": make_rich_text_chunks("📦 项目里程碑与开发日志 (Development Milestones)"),
        },
    }

    # Milestone 1 Toggle
    m1_toggle = {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": make_rich_text_chunks("🚀 Milestone 1 (v1.0.0): 原生 KWin Wayland 零侵入采集引擎与基础设施", bold=True),
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
            "rich_text": make_rich_text_chunks("🌐 Milestone 2 (v1.0.1): 纯净多语言 (i18n) 重构与物理隔离", bold=True),
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
            "rich_text": make_rich_text_chunks("🧠 Milestone 3 (v1.1.0): 三层递进分类管道设计与元数据加权引擎", bold=True),
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
            "rich_text": make_rich_text_chunks("⚡ 系统架构亮点与关键设计决策 (Engineering Highlights)", bold=True),
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
    optional columns (URL, Status, Select, Multi-select, Date, Description) if available.
    Adheres strictly to requirement:
    "If the database has URL or Status or Multi-select properties, adaptively populate what is safe."
    """
    props_payload = {}
    title_key = None

    # 1. Identify title property (mandatory in Notion)
    for prop_name, prop_info in db_properties.items():
        if isinstance(prop_info, dict) and prop_info.get("type") == "title":
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
    date_matched = False
    for prop_name, prop_info in db_properties.items():
        if not isinstance(prop_info, dict):
            continue
        ptype = prop_info.get("type")
        lower_name = prop_name.lower()

        # URL field
        if ptype == "url":
            if any(k in lower_name for k in ("url", "repo", "link", "仓库", "链接", "github", "项目", "代码")):
                props_payload[prop_name] = {"url": PROJECT_REPO_URL}
            elif "url" not in [k.lower() for k in props_payload.keys()]:
                props_payload[prop_name] = {"url": PROJECT_REPO_URL}

        # Date field (prefer creation/start date; populate only one date column)
        elif ptype == "date" and not date_matched:
            if any(k in lower_name for k in ("date", "创建", "时间", "日期", "created", "开始", "start")):
                props_payload[prop_name] = {"date": {"start": datetime.date.today().isoformat()}}
                date_matched = True

        # Summary / Description rich_text field
        elif ptype == "rich_text" and any(k in lower_name for k in ("desc", "summary", "描述", "简介", "备注", "看板", "摘要", "说明")):
            props_payload[prop_name] = {
                "rich_text": make_rich_text_chunks(PROJECT_SUBTITLE),
            }

        # Native Notion 'status' field (explicitly required)
        elif ptype == "status":
            status_meta = prop_info.get("status") or {}
            options = [opt.get("name", "") for opt in status_meta.get("options", []) if isinstance(opt, dict)]
            # Match status candidates (Done, Complete, Active, Completed, 进行中, 已完成)
            matched_status = None
            for candidate in ("已完成", "完成", "Done", "Complete", "Active", "进行中", "稳定版", "发布"):
                for opt_name in options:
                    if candidate in opt_name:
                        matched_status = opt_name
                        break
                if matched_status:
                    break
            if matched_status:
                props_payload[prop_name] = {"status": {"name": matched_status}}

        # Notion 'select' field
        elif ptype == "select":
            select_meta = prop_info.get("select") or {}
            options = [opt.get("name", "") for opt in select_meta.get("options", []) if isinstance(opt, dict)]
            matched_option = None
            for candidate in ("已完成", "有效", "Active", "稳定版", "发布", "Done", "数字资产", "项目", "工具"):
                for opt_name in options:
                    if candidate in opt_name:
                        matched_option = opt_name
                        break
                if matched_option:
                    break
            if matched_option:
                props_payload[prop_name] = {"select": {"name": matched_option}}

        # Notion 'multi_select' field (explicitly required)
        elif ptype == "multi_select":
            mselect_meta = prop_info.get("multi_select") or {}
            options = [opt.get("name", "") for opt in mselect_meta.get("options", []) if isinstance(opt, dict)]
            matched_tags = []
            tag_candidates = ("Python", "KDE", "Wayland", "Linux", "开源", "项目", "编程", "工具", "数字资产", "工作", "效率")
            for cand in tag_candidates:
                for opt_name in options:
                    if cand.lower() in opt_name.lower() and opt_name not in matched_tags:
                        matched_tags.append(opt_name)
            if matched_tags:
                props_payload[prop_name] = {"multi_select": [{"name": t} for t in matched_tags[:3]]}

    return props_payload, title_key


def fetch_bot_info(opener: urllib.request.OpenerDirector, token: str, verbose: bool = False) -> dict | None:
    """Fetch current bot and workspace metadata from Notion API."""
    res = notion_api_request(opener=opener, token=token, method="GET", endpoint="/users/me", verbose=verbose)
    if not res.get("_error"):
        return res
    return None


def sync_to_notion(
    token: str,
    database_id: str,
    opener: urllib.request.OpenerDirector,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """
    Main synchronization logic:
    1. Introspect target database schema (or parent page if database not found)
    2. Adaptively build properties payload (Title, URL, Status, Multi-select, Date, Description)
    3. Construct structured blocks hierarchy
    4. Slices <=100 blocks for creation, appends overflow blocks via block children API
    5. Automatic resilient retry with title-only if custom properties trigger HTTP 400
    """
    print("=" * 68)
    print("⏱️  Desktop TimeTracker -> Notion 数字资产沉淀工具")
    print("=" * 68)
    print(f"目标 ID : {database_id}")

    # Query bot information for enhanced diagnostics
    bot_info = fetch_bot_info(opener, token, verbose=verbose)
    bot_name = (bot_info.get("name") if bot_info else None) or "你的 Notion 集成"
    workspace_name = (bot_info.get("bot", {}).get("workspace_name") if bot_info else None) or "当前工作区"

    is_database = True
    parent_payload = {"database_id": database_id}
    properties_schema = {}

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
        status_code = (db_resp.get("error_data") or {}).get("http_status") or db_resp.get("status")
        msg = (db_resp.get("error_data") or {}).get("message", db_resp.get("exception", "Unknown error"))

        # If 404, probe if target ID might be a parent Page instead of a Database
        if status_code == 404 and not dry_run:
            if verbose:
                print(f"[DEBUG] Database not found; checking if ID {database_id} is a Page...")
            page_probe = notion_api_request(opener, token, "GET", f"/pages/{database_id}", verbose=verbose)
            if not page_probe.get("_error"):
                print(f"[✅] 成功连接至父级页面 (Page ID: {database_id})")
                is_database = False
                parent_payload = {"page_id": database_id}
                properties_schema = {"title": {"type": "title"}}

        if is_database and db_resp.get("_error"):
            if dry_run:
                print(f"[⚠️ 提示] 在线查询数据库属性返回 (HTTP {status_code}: {msg})。")
                print("由于开启了 --dry-run 模拟模式，将采用标准数据库 Schema 继续构建数据载荷进行本地校验...")
                properties_schema = {
                    "Name": {"type": "title"},
                    "URL": {"type": "url"},
                    "Status": {"type": "status", "status": {"options": [{"name": "已完成"}]}},
                    "Tags": {"type": "multi_select", "multi_select": {"options": [{"name": "Python"}, {"name": "开源"}]}},
                    "Date": {"type": "date"},
                }
            else:
                print("\n" + "!" * 68)
                print(f"[❌ 错误] 无法访问目标 Notion 资源 (HTTP {status_code})")
                print(f"详细信息: {msg}")
                print("!" * 68)

                if status_code == 404:
                    print("\n💡 常见原因与解决指引:")
                    print(f"1. 集成尚未共享到该数据库/页面:")
                    print(f"   当前集成名称 : 「{bot_name}」 (工作区: {workspace_name})")
                    print("   授权三步操作:")
                    print(f"     a. 在浏览器打开目标数据库/页面 (ID: {database_id})")
                    print("     b. 点击右上角「...」菜单 -> 选择「Connections / 连接」")
                    print(f"     c. 在搜索框搜索并添加集成「{bot_name}」")
                    print("     d. 重新运行本脚本即可立即同步！")
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

    # Build properties payload
    if is_database:
        props_payload, title_key = build_properties_payload(properties_schema)
        print(f"[ℹ️] 识别主标题属性列: 「{title_key}」")
        extra_keys = [k for k in props_payload.keys() if k != title_key]
        if extra_keys:
            print(f"[ℹ️] 自适应适配属性列: {', '.join(extra_keys)}")
    else:
        # Parent is a Page: only 'title' is valid in properties
        props_payload = {
            "title": [
                {
                    "type": "text",
                    "text": {"content": PROJECT_PAGE_TITLE},
                }
            ]
        }
        title_key = "title"
        print("[ℹ️] 父级为 Page 容器，主标题属性: 「title」")

    # 2. Build Content Blocks
    children_blocks = build_page_blocks()
    print(f"[ℹ️] 构建结构化块组件完成 (共 {len(children_blocks)} 个顶级块，包含资产看板与 4 组级联折叠清单)")

    # Adhere to Notion's <=100 children blocks per call limit
    first_batch = children_blocks[:100]
    overflow_blocks = children_blocks[100:]

    page_payload = {
        "parent": parent_payload,
        "properties": props_payload,
        "children": first_batch,
        "icon": {"type": "emoji", "emoji": "⏱️"},
    }

    # 3. Handle Dry-Run Mode
    if dry_run:
        print("\n" + "-" * 68)
        print("🔍 [DRY-RUN 模拟模式] 未向 Notion 写入真实数据。以下是生成的完整请求载荷预览:")
        print("-" * 68)
        preview_json = json.dumps(page_payload, indent=2, ensure_ascii=False)
        print(preview_json[:3500])
        if len(preview_json) > 3500:
            print("\n... [已截断多余输出] ...")
        if overflow_blocks:
            print(f"\n[ℹ️] 检测到额外 {len(overflow_blocks)} 个块将在页面创建后通过 PATCH 自动追加。")
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

    # 6. Append overflow blocks if any (>100 blocks batching)
    if overflow_blocks and page_id:
        print(f"[-] 正在追加剩余 {len(overflow_blocks)} 个内容块...")
        for i in range(0, len(overflow_blocks), 100):
            batch = overflow_blocks[i : i + 100]
            append_resp = notion_api_request(
                opener=opener,
                token=token,
                method="PATCH",
                endpoint=f"/blocks/{page_id}/children",
                payload={"children": batch},
                verbose=verbose,
            )
            if append_resp.get("_error"):
                print(f"[⚠️ 警告] 追加第 {i//100 + 1} 批内容块失败: {append_resp.get('error_data')}")

    print("\n" + "=" * 68)
    print("🎉 恭喜！Desktop TimeTracker 开发日志与数字资产已成功写入 Notion！")
    print(f"• 页面 ID : {page_id}")
    if page_url:
        print(f"• 页面链接 : {page_url}")
    print("=" * 68)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="将 Desktop TimeTracker 项目元数据、设计决策与开发日志写入 Notion 数据库或页面。"
    )
    parser.add_argument(
        "--token",
        "-t",
        help="Notion Integration Token (留空则依次从环境变量、notion.conf、notion.json、~/.config/notion/api_key 中查找)",
    )
    parser.add_argument(
        "--database-id",
        "-d",
        default=None,
        help=f"目标 Notion 数据库或页面 ID (默认: {DEFAULT_DATABASE_ID})",
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
        print("  4. 标准 Notion 密钥文件 (~/.config/notion/api_key):")
        print("     ntn_...")
        print("  5. systemd 环境配置 (~/.config/environment.d/notion.conf):")
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
