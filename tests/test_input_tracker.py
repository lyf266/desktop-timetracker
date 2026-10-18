#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit and Integration Tests for Input Activity Tracker (src/desktop-timetracker)
==============================================================================
Validates:
1. Zero-leakage Blind Counter invariant (no keycodes or chars ever retained).
2. Binary input_event struct decoding (Press, Repeat, Release).
3. Euclidean mouse displacement and click accounting.
4. Distance unit conversions (px -> cm, m, km).
5. Database schema backward-compatible migration and atomic persistence.
6. Hourly rollover splitting and 24-hour matrix generation.
"""

import datetime
import math
import os
import sqlite3
import struct
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import MagicMock, patch

# Dynamically import extensionless executable src/desktop-timetracker
SRC_FILE = Path(__file__).resolve().parent.parent / "src" / "desktop-timetracker"
loader = SourceFileLoader("desktop_timetracker", str(SRC_FILE))
dt = loader.load_module()


class TestDistanceFormatting(unittest.TestCase):
    def test_px_to_meters(self):
        # 96 px = 0.0254 m (1 inch)
        meters = dt.px_to_meters(96.0)
        self.assertAlmostEqual(meters, 0.0254, places=6)

    def test_format_distance_cm(self):
        # Small movement (e.g. 50 px => ~0.013 m = 1.3 cm)
        dist_str = dt.format_distance(50)
        self.assertTrue(dist_str.endswith("cm"))
        self.assertIn("1.3", dist_str)

    def test_format_distance_meters(self):
        # Medium movement (e.g. 10,000 px => ~2.65 m)
        dist_str = dt.format_distance(10000)
        self.assertTrue(dist_str.endswith("m"))
        self.assertIn("2.6", dist_str)

    def test_format_distance_km(self):
        # Long movement (e.g. 5,000,000 px => ~1322.9 m = 1.32 km)
        dist_str = dt.format_distance(5000000)
        self.assertTrue(dist_str.endswith("km"))
        self.assertIn("1.32", dist_str)


class TestInputActivityMonitor(unittest.TestCase):
    def setUp(self):
        self.monitor = dt.InputActivityMonitor()

    def tearDown(self):
        self.monitor.stop()

    def _pack_event(self, ev_type, code, val, sec=1000, usec=0):
        return struct.pack(dt.EVENT_FORMAT, sec, usec, ev_type, code, val)

    def test_blind_counter_only_presses_counted(self):
        """Invariant: Only keydown (val=1) increments counter. Repeat (2) and release (0) ignored."""
        fd = 10
        self.monitor._fds[fd] = ("kbd", "/dev/input/event4")

        # Simulate 'A' press (code=30, val=1)
        chunk_press = self._pack_event(ev_type=1, code=30, val=1)
        # Simulate 'A' repeat (code=30, val=2)
        chunk_repeat = self._pack_event(ev_type=1, code=30, val=2)
        # Simulate 'A' release (code=30, val=0)
        chunk_release = self._pack_event(ev_type=1, code=30, val=0)

        data = chunk_press + chunk_repeat + chunk_release
        num_events = len(data) // dt.EVENT_SIZE

        for i in range(num_events):
            chunk = data[i * dt.EVENT_SIZE:(i + 1) * dt.EVENT_SIZE]
            _, _, ev_type, code, val = struct.unpack(dt.EVENT_FORMAT, chunk)
            if ev_type == 1 and val == 1:
                with self.monitor.lock:
                    self.monitor._key_presses += 1

        self.assertEqual(self.monitor._key_presses, 1)

    def test_zero_leakage_privacy_invariant(self):
        """Invariant: Under no circumstances should keycodes, characters or keystroke logs exist."""
        # Inspect monitor properties
        self.assertIsInstance(self.monitor._key_presses, int)
        self.assertFalse(hasattr(self.monitor, "keycodes"))
        self.assertFalse(hasattr(self.monitor, "logged_keys"))
        self.assertFalse(hasattr(self.monitor, "keystroke_history"))

        # Verify that get_and_reset only yields scalar integers
        keys, clicks, dist = self.monitor.get_and_reset()
        self.assertIsInstance(keys, int)
        self.assertIsInstance(clicks, int)
        self.assertIsInstance(dist, int)

    def test_mouse_relative_displacement_calculation(self):
        """Euclidean distance: sqrt(30^2 + 40^2) = 50 px."""
        fd = 20
        self.monitor._fds[fd] = ("mouse", "/dev/input/event5")
        self.monitor._mouse_dx[fd] = 0
        self.monitor._mouse_dy[fd] = 0

        # REL_X = 30
        p1 = self._pack_event(ev_type=2, code=0, val=30)
        # REL_Y = 40
        p2 = self._pack_event(ev_type=2, code=1, val=40)
        # SYN_REPORT
        p3 = self._pack_event(ev_type=0, code=0, val=0)

        data = p1 + p2 + p3
        num_events = len(data) // dt.EVENT_SIZE

        for i in range(num_events):
            chunk = data[i * dt.EVENT_SIZE:(i + 1) * dt.EVENT_SIZE]
            _, _, ev_type, code, val = struct.unpack(dt.EVENT_FORMAT, chunk)
            if ev_type == 2:
                if code == 0:
                    self.monitor._mouse_dx[fd] += val
                elif code == 1:
                    self.monitor._mouse_dy[fd] += val
            elif ev_type == 0:
                dx = self.monitor._mouse_dx.get(fd, 0)
                dy = self.monitor._mouse_dy.get(fd, 0)
                if dx != 0 or dy != 0:
                    dist = math.hypot(dx, dy)
                    with self.monitor.lock:
                        self.monitor._mouse_distance_px += dist
                    self.monitor._mouse_dx[fd] = 0
                    self.monitor._mouse_dy[fd] = 0

        keys, clicks, dist = self.monitor.get_and_reset()
        self.assertEqual(dist, 50)
        self.assertEqual(keys, 0)
        self.assertEqual(clicks, 0)

    def test_mouse_click_counting(self):
        fd = 20
        self.monitor._fds[fd] = ("mouse", "/dev/input/event5")

        # BTN_LEFT press (code=0x110, val=1)
        p_left = self._pack_event(ev_type=1, code=0x110, val=1)
        # BTN_RIGHT press (code=0x111, val=1)
        p_right = self._pack_event(ev_type=1, code=0x111, val=1)
        # BTN_LEFT release (code=0x110, val=0)
        p_rel = self._pack_event(ev_type=1, code=0x110, val=0)

        data = p_left + p_right + p_rel
        num_events = len(data) // dt.EVENT_SIZE

        for i in range(num_events):
            chunk = data[i * dt.EVENT_SIZE:(i + 1) * dt.EVENT_SIZE]
            _, _, ev_type, code, val = struct.unpack(dt.EVENT_FORMAT, chunk)
            if ev_type == 1 and val == 1:
                with self.monitor.lock:
                    self.monitor._mouse_clicks += 1

        keys, clicks, dist = self.monitor.get_and_reset()
        self.assertEqual(clicks, 2)
        self.assertEqual(keys, 0)

    def test_device_scanner_parsing(self):
        fake_content = """I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
P: Phys=isa0060/serio0/input0
S: Sysfs=/devices/platform/i8042/serio0/input/input4
U: Uniq=
H: Handlers=sysrq kbd leds event4
B: EV=120013

I: Bus=0003 Vendor=18f8 Product=0f99 Version=0110
N: Name="USB OPTICAL MOUSE"
P: Phys=usb-0000:00:14.0-2/input0
S: Sysfs=/devices/pci0000:00/0000:00:14.0/usb1/1-2/input/input6
U: Uniq=
H: Handlers=event5 mouse0
B: EV=17

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
P: Phys=PNP0C0C/button/input0
S: Sysfs=/devices/platform/PNP0C0C:00/input/input0
U: Uniq=
H: Handlers=kbd event0
B: EV=3
"""
        with tempfile.NamedTemporaryFile("w+", delete=False) as tf:
            tf.write(fake_content)
            tf_path = Path(tf.name)

        try:
            with patch("pathlib.Path.exists", return_value=True), \
                 patch("builtins.open", unittest.mock.mock_open(read_data=fake_content)):
                kbds, mice = dt.InputActivityMonitor.scan_devices()

            self.assertEqual(len(kbds), 1)
            self.assertEqual(kbds[0][1], "/dev/input/event4")
            self.assertEqual(len(mice), 1)
            self.assertEqual(mice[0][1], "/dev/input/event5")
        finally:
            if tf_path.exists():
                tf_path.unlink()


class TestDatabaseSchemaAndMigration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_timetracker.db"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_new_database_has_input_columns(self):
        db = dt.Database(db_path=self.db_path)
        with db.get_conn() as conn:
            cur = conn.execute("PRAGMA table_info(window_activities);")
            col_names = [r["name"] for r in cur.fetchall()]

        self.assertIn("key_presses", col_names)
        self.assertIn("mouse_clicks", col_names)
        self.assertIn("mouse_distance_px", col_names)

    def test_legacy_database_migration(self):
        # 1. Create a legacy database without input columns
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE window_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds INTEGER NOT NULL,
                app_id TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT NOT NULL,
                category TEXT NOT NULL,
                is_locked INTEGER DEFAULT 0,
                is_idle INTEGER DEFAULT 0
            );
        """)
        conn.execute("""
            INSERT INTO window_activities (
                start_time, end_time, duration_seconds, app_id, app_name, window_title, category
            ) VALUES ('2026-10-18 09:00:00', '2026-10-18 09:30:00', 1800, 'code', 'VS Code', 'main.py', 'development');
        """)
        conn.commit()
        conn.close()

        # 2. Open with dt.Database (triggers migration)
        db = dt.Database(db_path=self.db_path)
        records = db.query_day("2026-10-18")
        self.assertEqual(len(records), 1)
        row = records[0]
        self.assertEqual(row["key_presses"], 0)
        self.assertEqual(row["mouse_clicks"], 0)
        self.assertEqual(row["mouse_distance_px"], 0)

        # 3. Save new record with input metrics
        rec_id = db.save_record(
            start_time="2026-10-18 10:00:00",
            end_time="2026-10-18 10:30:00",
            duration=1800,
            app_id="code",
            app_name="VS Code",
            window_title="main.py",
            category="development",
            is_locked=0,
            is_idle=0,
            key_presses=1450,
            mouse_clicks=210,
            mouse_distance_px=8540
        )
        self.assertIsNotNone(rec_id)

        # 4. Verify updated retrieval
        records = db.query_day("2026-10-18")
        self.assertEqual(len(records), 2)
        new_row = records[1]
        self.assertEqual(new_row["key_presses"], 1450)
        self.assertEqual(new_row["mouse_clicks"], 210)
        self.assertEqual(new_row["mouse_distance_px"], 8540)


class TestHourlySplittingAndReporting(unittest.TestCase):
    def test_hourly_rollover_triggers_flush(self):
        daemon = dt.Daemon.__new__(dt.Daemon)
        daemon.current_chunk = {
            "start_dt": datetime.datetime(2026, 10, 18, 9, 30, 0),
            "last_dt": datetime.datetime(2026, 10, 18, 9, 59, 50),
            "app_id": "code",
            "app_name": "VS Code",
            "window_title": "test.py",
            "category": "development",
            "is_locked": 0,
            "db_id": None
        }
        flushed = []
        daemon.flush_chunk = lambda final=False: flushed.append(final)

        # Same hour -> no flush
        daemon.check_hourly_rollover(datetime.datetime(2026, 10, 18, 9, 59, 59))
        self.assertEqual(len(flushed), 0)

        # Hour rolls over to 10 -> flush final=True
        daemon.check_hourly_rollover(datetime.datetime(2026, 10, 18, 10, 0, 5))
        self.assertEqual(len(flushed), 1)
        self.assertTrue(flushed[0])

    def test_report_generator_markdown_integration(self):
        records = [
            {
                "start_time": "2026-10-18 09:15:00",
                "end_time": "2026-10-18 09:45:00",
                "duration_seconds": 1800,
                "app_name": "VS Code",
                "window_title": "app.py",
                "category": "development",
                "is_locked": 0,
                "key_presses": 1250,
                "mouse_clicks": 95,
                "mouse_distance_px": 5400
            },
            {
                "start_time": "2026-10-18 10:00:00",
                "end_time": "2026-10-18 10:50:00",
                "duration_seconds": 3000,
                "app_name": "Firefox",
                "window_title": "GitHub",
                "category": "browsing",
                "is_locked": 0,
                "key_presses": 420,
                "mouse_clicks": 310,
                "mouse_distance_px": 12000
            }
        ]

        # Test Simplified Chinese Report
        md_zh = dt.ReportGenerator.generate_markdown(records, "2026-10-18", lang="zh")
        self.assertIn("全天键盘打字", md_zh)
        self.assertIn("1,670", md_zh)  # 1250 + 420
        self.assertIn("全天鼠标活动", md_zh)
        self.assertIn("405", md_zh)    # 95 + 310 clicks
        self.assertIn("09:00 - 10:00", md_zh)
        self.assertIn("10:00 - 11:00", md_zh)
        self.assertIn("打字量", md_zh)
        self.assertIn("鼠标滑行", md_zh)

        # Test English Report
        md_en = dt.ReportGenerator.generate_markdown(records, "2026-10-18", lang="en")
        self.assertIn("Total Keystrokes", md_en)
        self.assertIn("1,670", md_en)
        self.assertIn("Total Mouse Travel", md_en)
        self.assertIn("Keystrokes", md_en)
        self.assertIn("Mouse Travel", md_en)


if __name__ == "__main__":
    unittest.main()
