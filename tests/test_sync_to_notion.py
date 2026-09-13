#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit and Integration Tests for Notion Sync Script (scripts/sync_to_notion.py)
=============================================================================
Tests all core functions:
- URL and UUID extraction regex
- Multi-tier token resolution (CLI > ENV > conf > json > ~/.config/notion/api_key)
- Whitespace env fallback handling
- Target database/page ID resolution
- Block construction, <=100 batching, and >2000 char rich text lossless chunking
- Dynamic schema introspection: Title, URL, Date, Rich-text, Status, Select, Multi-select
- Safe handling of None/null schema properties
- Fallback retry on HTTP 400
- Dual database/page parent support
- Dry-run verification
"""

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import sync_to_notion


class TestCleanUuid(unittest.TestCase):
    def test_clean_uuid_with_hyphens(self):
        raw = "3b9f94c6-7e98-4bf9-9347-18b861d8d279"
        expected = "3b9f94c67e984bf9934718b861d8d279"
        self.assertEqual(sync_to_notion.clean_uuid(raw), expected)

    def test_clean_uuid_with_spaces_and_newlines(self):
        raw = "  3b9f94c6-7e98-4bf9-9347-18b861d8d279 \n"
        expected = "3b9f94c67e984bf9934718b861d8d279"
        self.assertEqual(sync_to_notion.clean_uuid(raw), expected)

    def test_clean_uuid_empty_or_none(self):
        self.assertEqual(sync_to_notion.clean_uuid(""), "")
        self.assertEqual(sync_to_notion.clean_uuid(None), "")

    def test_clean_uuid_from_notion_url(self):
        url = "https://www.notion.so/workspace/3b9f94c67e984bf9934718b861d8d279?v=12345678"
        expected = "3b9f94c67e984bf9934718b861d8d279"
        self.assertEqual(sync_to_notion.clean_uuid(url), expected)

    def test_clean_uuid_from_hyphenated_notion_url(self):
        url = "https://notion.so/my-team/3b9f94c6-7e98-4bf9-9347-18b861d8d279"
        expected = "3b9f94c67e984bf9934718b861d8d279"
        self.assertEqual(sync_to_notion.clean_uuid(url), expected)


class TestResolveToken(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        os.environ.pop("NOTION_API_KEY", None)
        os.environ.pop("NOTION_TOKEN", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_cli_token_has_highest_priority(self):
        os.environ["NOTION_TOKEN"] = "env_token_value"
        token, source = sync_to_notion.resolve_notion_token(cli_token="cli_token_val")
        self.assertEqual(token, "cli_token_val")
        self.assertIn("CLI argument", source)

    def test_env_token_resolution(self):
        os.environ["NOTION_API_KEY"] = "api_key_val"
        token, source = sync_to_notion.resolve_notion_token()
        self.assertEqual(token, "api_key_val")
        self.assertIn("NOTION_API_KEY", source)

        os.environ.pop("NOTION_API_KEY")
        os.environ["NOTION_TOKEN"] = "notion_token_val"
        token, source = sync_to_notion.resolve_notion_token()
        self.assertEqual(token, "notion_token_val")
        self.assertIn("NOTION_TOKEN", source)

    def test_whitespace_in_api_key_falls_back_to_token(self):
        os.environ["NOTION_API_KEY"] = "   "
        os.environ["NOTION_TOKEN"] = "valid_token_from_env"
        token, source = sync_to_notion.resolve_notion_token()
        self.assertEqual(token, "valid_token_from_env")
        self.assertIn("NOTION_TOKEN", source)

    def test_conf_file_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_home = Path(tmpdir)
            conf_dir = tmp_home / ".config" / "environment.d"
            conf_dir.mkdir(parents=True)
            conf_file = conf_dir / "notion.conf"
            conf_file.write_text('NOTION_TOKEN="conf_secret_123"\n', encoding="utf-8")

            with patch("pathlib.Path.home", return_value=tmp_home):
                token, source = sync_to_notion.resolve_notion_token()
                self.assertEqual(token, "conf_secret_123")
                self.assertIn("notion.conf", source)

    def test_json_file_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_home = Path(tmpdir)
            cfg_dir = tmp_home / ".config" / "timetracker"
            cfg_dir.mkdir(parents=True)
            json_file = cfg_dir / "notion.json"
            json_file.write_text(json.dumps({"notion_token": "json_secret_456"}), encoding="utf-8")

            with patch("pathlib.Path.home", return_value=tmp_home):
                token, source = sync_to_notion.resolve_notion_token()
                self.assertEqual(token, "json_secret_456")
                self.assertIn("notion.json", source)

    def test_dot_config_notion_api_key_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_home = Path(tmpdir)
            notion_dir = tmp_home / ".config" / "notion"
            notion_dir.mkdir(parents=True)
            key_file = notion_dir / "api_key"
            key_file.write_text("ntn_standard_dot_config_key\n", encoding="utf-8")

            with patch("pathlib.Path.home", return_value=tmp_home):
                token, source = sync_to_notion.resolve_notion_token()
                self.assertEqual(token, "ntn_standard_dot_config_key")
                self.assertIn("api_key", source)

    def test_no_token_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_home = Path(tmpdir)
            with patch("pathlib.Path.home", return_value=tmp_home):
                token, source = sync_to_notion.resolve_notion_token()
                self.assertIsNone(token)
                self.assertIsNone(source)


class TestResolveDatabaseId(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        os.environ.pop("NOTION_DATABASE_ID", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_cli_db_id_priority(self):
        raw = "11111111-2222-3333-4444-555555555555"
        db_id, source = sync_to_notion.resolve_database_id(cli_db_id=raw)
        self.assertEqual(db_id, "11111111222233334444555555555555")
        self.assertIn("CLI argument", source)

    def test_cli_db_id_url_parsing(self):
        raw = "https://notion.so/workspace/11111111-2222-3333-4444-555555555555?v=view"
        db_id, source = sync_to_notion.resolve_database_id(cli_db_id=raw)
        self.assertEqual(db_id, "11111111222233334444555555555555")

    def test_env_db_id(self):
        os.environ["NOTION_DATABASE_ID"] = "22222222-3333-4444-5555-666666666666"
        db_id, source = sync_to_notion.resolve_database_id()
        self.assertEqual(db_id, "22222222333344445555666666666666")
        self.assertIn("Environment variable", source)

    def test_default_constant_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_home = Path(tmpdir)
            with patch("pathlib.Path.home", return_value=tmp_home):
                db_id, source = sync_to_notion.resolve_database_id()
                self.assertEqual(db_id, sync_to_notion.clean_uuid(sync_to_notion.DEFAULT_DATABASE_ID))
                self.assertIn("Default constant", source)


class TestBuildPageBlocks(unittest.TestCase):
    def test_blocks_count_and_structure(self):
        blocks = sync_to_notion.build_page_blocks()
        self.assertLessEqual(len(blocks), 100)
        self.assertGreaterEqual(len(blocks), 6)

        # Block 0: Callout
        callout = blocks[0]
        self.assertEqual(callout["type"], "callout")
        self.assertEqual(callout["callout"]["icon"]["emoji"], "⏱️")
        self.assertEqual(callout["callout"]["color"], "blue_background")

        # Verify callout rich text contains required metadata
        callout_text = "".join(t["text"]["content"] for t in callout["callout"]["rich_text"])
        self.assertIn("Desktop TimeTracker (timetrack)", callout_text)
        self.assertIn("Python 3", callout_text)
        self.assertIn("KDE Plasma 6 Wayland", callout_text)
        self.assertIn("~13MB RAM", callout_text)
        self.assertIn("<0.1% CPU", callout_text)
        self.assertIn("MIT License", callout_text)
        self.assertIn("https://github.com/lyf266/desktop-timetracker", callout_text)

        # Block 1: Divider
        self.assertEqual(blocks[1]["type"], "divider")

        # Block 2: Heading 2
        self.assertEqual(blocks[2]["type"], "heading_2")

        # Toggle Blocks: M1, M2, M3, Arch
        toggles = [b for b in blocks if b.get("type") == "toggle"]
        self.assertEqual(len(toggles), 4)

        # Check Milestone 1
        m1_text = toggles[0]["toggle"]["rich_text"][0]["text"]["content"]
        self.assertIn("Milestone 1 (v1.0.0)", m1_text)
        m1_children = toggles[0]["toggle"]["children"]
        self.assertGreater(len(m1_children), 0)
        m1_children_text = " ".join(
            "".join(rt["text"]["content"] for rt in c["bulleted_list_item"]["rich_text"])
            for c in m1_children
        )
        self.assertIn("KWin Wayland", m1_children_text)
        self.assertIn("ScreenSaver", m1_children_text)
        self.assertIn("SQLite WAL", m1_children_text)
        self.assertIn("Markdown", m1_children_text)

        # Check Milestone 2
        m2_text = toggles[1]["toggle"]["rich_text"][0]["text"]["content"]
        self.assertIn("Milestone 2 (v1.0.1)", m2_text)
        m2_children_text = " ".join(
            "".join(rt["text"]["content"] for rt in c["bulleted_list_item"]["rich_text"])
            for c in toggles[1]["toggle"]["children"]
        )
        self.assertIn("i18n", m2_children_text)
        self.assertIn("timetrack lang", m2_children_text)
        self.assertIn("README_zh.md", m2_children_text)

        # Check Milestone 3
        m3_text = toggles[2]["toggle"]["rich_text"][0]["text"]["content"]
        self.assertIn("Milestone 3 (v1.1.0)", m3_text)
        m3_children_text = " ".join(
            "".join(rt["text"]["content"] for rt in c["bulleted_list_item"]["rich_text"])
            for c in toggles[2]["toggle"]["children"]
        )
        self.assertIn("rules.json", m3_children_text)
        self.assertIn(".desktop", m3_children_text)
        self.assertIn("TerminalEmulator", m3_children_text)

        # Check max 2000 chars per text object limit
        def check_text_length(obj):
            if isinstance(obj, dict):
                if obj.get("type") == "text" and "content" in obj.get("text", {}):
                    self.assertLessEqual(len(obj["text"]["content"]), 2000)
                for v in obj.values():
                    check_text_length(v)
            elif isinstance(obj, list):
                for item in obj:
                    check_text_length(item)

        check_text_length(blocks)

    def test_make_rich_text_chunks_does_not_truncate_long_text(self):
        long_str = "X" * 4500
        chunks = sync_to_notion.make_rich_text_chunks(long_str)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(len(chunks[0]["text"]["content"]), 2000)
        self.assertEqual(len(chunks[1]["text"]["content"]), 2000)
        self.assertEqual(len(chunks[2]["text"]["content"]), 500)
        # Verify complete content preserved losslessly
        reconstructed = "".join(c["text"]["content"] for c in chunks)
        self.assertEqual(reconstructed, long_str)


class TestBuildPropertiesPayload(unittest.TestCase):
    def test_adaptive_property_mapping_all_types(self):
        schema = {
            "项目名称": {"id": "title_id", "type": "title"},
            "项目仓库": {"id": "url_id", "type": "url"},
            "创建日期": {"id": "date_id", "type": "date"},
            "项目摘要": {"id": "desc_id", "type": "rich_text"},
            "状态": {
                "id": "status_id",
                "type": "status",
                "status": {"options": [{"name": "未开始"}, {"name": "进行中"}, {"name": "已完成"}]},
            },
            "类型": {
                "id": "select_id",
                "type": "select",
                "select": {"options": [{"name": "💡 想法"}, {"name": "📦 项目"}]},
            },
            "标签": {
                "id": "multi_id",
                "type": "multi_select",
                "multi_select": {"options": [{"name": "Python"}, {"name": "开源"}, {"name": "硬件"}]},
            },
        }
        payload, title_key = sync_to_notion.build_properties_payload(schema)

        self.assertEqual(title_key, "项目名称")
        self.assertIn("项目名称", payload)
        self.assertEqual(payload["项目名称"]["title"][0]["text"]["content"], sync_to_notion.PROJECT_PAGE_TITLE)

        # URL
        self.assertIn("项目仓库", payload)
        self.assertEqual(payload["项目仓库"]["url"], sync_to_notion.PROJECT_REPO_URL)

        # Date
        self.assertIn("创建日期", payload)
        self.assertIn("start", payload["创建日期"]["date"])

        # Rich text (摘要)
        self.assertIn("项目摘要", payload)
        self.assertIn("rich_text", payload["项目摘要"])

        # Native Status
        self.assertIn("状态", payload)
        self.assertEqual(payload["状态"]["status"]["name"], "已完成")

        # Select (with emoji)
        self.assertIn("类型", payload)
        self.assertEqual(payload["类型"]["select"]["name"], "📦 项目")

        # Multi-select
        self.assertIn("标签", payload)
        names = [item["name"] for item in payload["标签"]["multi_select"]]
        self.assertIn("Python", names)
        self.assertIn("开源", names)

    def test_safe_handling_of_none_properties(self):
        # When Notion API returns null/None for select/status/multi_select
        schema = {
            "Name": {"type": "title"},
            "StatusCol": {"type": "status", "status": None},
            "SelectCol": {"type": "select", "select": None},
            "MultiCol": {"type": "multi_select", "multi_select": None},
        }
        payload, title_key = sync_to_notion.build_properties_payload(schema)
        self.assertEqual(title_key, "Name")
        self.assertEqual(len(payload), 1)

    def test_default_name_fallback_when_only_standard_title(self):
        schema = {"Name": {"id": "name_id", "type": "title"}}
        payload, title_key = sync_to_notion.build_properties_payload(schema)
        self.assertEqual(title_key, "Name")
        self.assertEqual(len(payload), 1)
        self.assertIn("Name", payload)


class TestSyncToNotionIntegration(unittest.TestCase):
    def test_successful_database_sync_mock(self):
        mock_opener = MagicMock()

        # Database schema response
        db_data = {
            "title": [{"plain_text": "数字资产库"}],
            "properties": {
                "名称": {"type": "title"},
                "URL": {"type": "url"},
                "状态": {"type": "status", "status": {"options": [{"name": "已完成"}]}},
            },
        }

        # Page creation response
        page_data = {
            "id": "mock_page_id_12345",
            "url": "https://www.notion.so/mock_page_id_12345",
        }

        bot_data = {"name": "AI Note-Taking", "bot": {"workspace_name": "Test Workspace"}}

        with patch.object(sync_to_notion, "notion_api_request") as mock_req:
            mock_req.side_effect = [bot_data, db_data, page_data]

            status = sync_to_notion.sync_to_notion(
                token="test_token",
                database_id="3b9f94c67e984bf9934718b861d8d279",
                opener=mock_opener,
                dry_run=False,
                verbose=False,
            )

            self.assertEqual(status, 0)
            self.assertEqual(mock_req.call_count, 3)
            # Call 0: /users/me
            self.assertEqual(mock_req.call_args_list[0][1]["endpoint"], "/users/me")
            # Call 1: GET /databases/3b9f94c67e984bf9934718b861d8d279
            self.assertEqual(mock_req.call_args_list[1][1]["method"], "GET")
            self.assertEqual(mock_req.call_args_list[1][1]["endpoint"], "/databases/3b9f94c67e984bf9934718b861d8d279")
            # Call 2: POST /pages
            self.assertEqual(mock_req.call_args_list[2][1]["method"], "POST")
            self.assertEqual(mock_req.call_args_list[2][1]["endpoint"], "/pages")

    def test_target_is_parent_page_fallback(self):
        mock_opener = MagicMock()
        bot_data = {"name": "AI Note-Taking"}

        # 1. GET /databases/id returns 404
        db_404 = {
            "_error": True,
            "status": 404,
            "error_data": {"http_status": 404, "message": "Could not find database"},
        }

        # 2. GET /pages/id succeeds (it's a page!)
        page_parent_data = {
            "id": "3b9f94c67e984bf9934718b861d8d279",
            "properties": {"title": {"type": "title"}},
        }

        # 3. POST /pages succeeds
        page_created = {
            "id": "child_page_id_777",
            "url": "https://notion.so/child_page_id_777",
        }

        with patch.object(sync_to_notion, "notion_api_request") as mock_req:
            mock_req.side_effect = [bot_data, db_404, page_parent_data, page_created]

            status = sync_to_notion.sync_to_notion(
                token="test_token",
                database_id="3b9f94c67e984bf9934718b861d8d279",
                opener=mock_opener,
                dry_run=False,
                verbose=False,
            )

            self.assertEqual(status, 0)
            self.assertEqual(mock_req.call_count, 4)
            # Verify parent payload used page_id
            created_payload = mock_req.call_args_list[3][1]["payload"]
            self.assertEqual(created_payload["parent"], {"page_id": "3b9f94c67e984bf9934718b861d8d279"})

    def test_database_404_error_handling(self):
        mock_opener = MagicMock()
        bot_data = {"name": "AI Note-Taking"}
        err_response = {
            "_error": True,
            "status": 404,
            "error_data": {
                "http_status": 404,
                "message": "Could not find database with ID: 3b9f94c67e984bf9934718b861d8d279.",
            },
        }

        with patch.object(sync_to_notion, "notion_api_request") as mock_req:
            mock_req.side_effect = [bot_data, err_response, err_response]
            status = sync_to_notion.sync_to_notion(
                token="test_token",
                database_id="3b9f94c67e984bf9934718b861d8d279",
                opener=mock_opener,
                dry_run=False,
                verbose=False,
            )
            self.assertEqual(status, 1)

    def test_bad_request_retry_fallback(self):
        mock_opener = MagicMock()
        bot_data = {"name": "AI Note-Taking"}
        db_data = {
            "title": [{"plain_text": "数字资产库"}],
            "properties": {
                "名称": {"type": "title"},
                "URL": {"type": "url"},
            },
        }
        fail_400 = {
            "_error": True,
            "status": 400,
            "error_data": {"http_status": 400, "message": "Validation error: property URL not allowed"},
        }
        page_success = {
            "id": "retry_success_id",
            "url": "https://notion.so/retry_success_id",
        }

        with patch.object(sync_to_notion, "notion_api_request") as mock_req:
            mock_req.side_effect = [bot_data, db_data, fail_400, page_success]

            status = sync_to_notion.sync_to_notion(
                token="test_token",
                database_id="3b9f94c67e984bf9934718b861d8d279",
                opener=mock_opener,
                dry_run=False,
                verbose=False,
            )
            self.assertEqual(status, 0)
            self.assertEqual(mock_req.call_count, 4)
            retry_payload = mock_req.call_args_list[3][1]["payload"]
            self.assertEqual(list(retry_payload["properties"].keys()), ["名称"])

    def test_dry_run_does_not_call_post_pages(self):
        mock_opener = MagicMock()
        bot_data = {"name": "AI Note-Taking"}
        db_data = {
            "title": [{"plain_text": "测试库"}],
            "properties": {"Name": {"type": "title"}},
        }

        with patch.object(sync_to_notion, "notion_api_request") as mock_req:
            mock_req.side_effect = [bot_data, db_data]
            status = sync_to_notion.sync_to_notion(
                token="test_token",
                database_id="3b9f94c67e984bf9934718b861d8d279",
                opener=mock_opener,
                dry_run=True,
                verbose=False,
            )
            self.assertEqual(status, 0)
            # Only GET /users/me and GET /databases called, no POST /pages
            self.assertEqual(mock_req.call_count, 2)
            self.assertEqual(mock_req.call_args_list[1][1]["endpoint"], "/databases/3b9f94c67e984bf9934718b861d8d279")

    def test_block_overflow_batching_appends_via_patch(self):
        # Test that when children blocks > 100, first 100 are sent in POST and rest in PATCH
        mock_opener = MagicMock()
        bot_data = {"name": "AI Note-Taking"}
        db_data = {"properties": {"Name": {"type": "title"}}}
        page_success = {"id": "page_with_many_blocks", "url": "https://notion.so/p"}
        patch_success = {"results": []}

        # Generate 150 dummy blocks
        many_blocks = [{"object": "block", "type": "divider", "divider": {}} for _ in range(150)]

        with patch.object(sync_to_notion, "build_page_blocks", return_value=many_blocks):
            with patch.object(sync_to_notion, "notion_api_request") as mock_req:
                mock_req.side_effect = [bot_data, db_data, page_success, patch_success]

                status = sync_to_notion.sync_to_notion(
                    token="test_token",
                    database_id="3b9f94c67e984bf9934718b861d8d279",
                    opener=mock_opener,
                    dry_run=False,
                    verbose=False,
                )

                self.assertEqual(status, 0)
                # Verify POST /pages had exactly 100 children
                post_payload = mock_req.call_args_list[2][1]["payload"]
                self.assertEqual(len(post_payload["children"]), 100)

                # Verify PATCH /blocks/{id}/children was called for remaining 50
                patch_call = mock_req.call_args_list[3]
                self.assertEqual(patch_call[1]["method"], "PATCH")
                self.assertEqual(patch_call[1]["endpoint"], "/blocks/page_with_many_blocks/children")
                self.assertEqual(len(patch_call[1]["payload"]["children"]), 50)


if __name__ == "__main__":
    unittest.main()
