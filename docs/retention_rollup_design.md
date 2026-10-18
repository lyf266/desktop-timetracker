# 📐 架构设计与技术规约：90天数据分层与天级 Rollup 归档 (Option 2 备选方案)

> **文档性质**：技术储备与备选架构方案（当前暂不激活，保留完整设计以备未来数据规模超标时启用）。  
> **关联分支**：`design/retention-rollup-backup`  
> **核心原则**：恪守“100% 纯本地、零外部依赖、零明文痕迹、有限有界存储（Bounded Invariant）”底线。

---

## 1. 架构目标与定位

当 `desktop-timetracker` 在单一桌面系统上连续运行多年（如 3~5 年以上），如果用户希望数据库文件大小被严格限制在确定性物理天花板（如 `<= 15MB`），即可激活本方案。

本方案将数据存储分为**两层生命周期**：
1. **热数据层（最近 90 天）**：保存在 `window_activities` 明细表中，记录每秒、每个窗口标题及键鼠打字量。
2. **冷数据层（> 90 天）**：自动通过 Rollup 聚合到 `daily_activity_summary` 天级汇总表中。
3. **明细物理裁剪（Pruning）**：90 天前的原始明细行物理删除，并执行增量整理，确保明细表总行数不超过 **~30,000 行**。

---

## 2. 数据库 Schema 设计

### 2.1 天级聚合表 `daily_activity_summary`
```sql
CREATE TABLE IF NOT EXISTS daily_activity_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,                         -- 格式: YYYY-MM-DD
    app_id TEXT NOT NULL,                       -- 应用程序 ID / desktop 文件名
    app_name TEXT NOT NULL,                     -- 友好展示名称
    category TEXT NOT NULL,                     -- 分类键名 (如 development, browsing 等)
    total_duration_seconds INTEGER NOT NULL,    -- 该应用当日总专注时长
    total_key_presses INTEGER DEFAULT 0,        -- 该应用当日总击键次数
    total_mouse_clicks INTEGER DEFAULT 0,       -- 该应用当日总鼠标点击数
    total_mouse_distance_px REAL DEFAULT 0.0,   -- 该应用当日总鼠标移动像素
    is_locked INTEGER DEFAULT 0                 -- 0: 活跃, 1: 锁屏挂机
);

CREATE INDEX IF NOT EXISTS idx_summary_date ON daily_activity_summary(date);
CREATE INDEX IF NOT EXISTS idx_summary_app ON daily_activity_summary(app_id);
CREATE INDEX IF NOT EXISTS idx_summary_cat ON daily_activity_summary(category);
CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_unique_day_app_lock
    ON daily_activity_summary(date, app_id, is_locked);
```

---

## 3. 归档与裁剪事务契约 (Rollup & Pruning Transaction)

### 3.1 触发时机
* **触发源**：后台守护进程 `Daemon.check_daily_rollover()` 在跨天（午夜 00:00）导出当日报表后触发。
* **频率**：每天仅执行一次，避免频繁打断。

### 3.2 归档原子事务流程
```python
def archive_and_prune_older_than_90_days(conn):
    """
    原子归档与清理 90 天前的明细数据
    """
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
    cutoff_timestamp = f"{cutoff_date} 00:00:00"

    with conn:
        # 1. 聚合归档至 daily_activity_summary (幂等插入)
        conn.execute("""
            INSERT INTO daily_activity_summary (
                date, app_id, app_name, category,
                total_duration_seconds, total_key_presses,
                total_mouse_clicks, total_mouse_distance_px, is_locked
            )
            SELECT 
                date(start_time) as d,
                app_id,
                app_name,
                category,
                SUM(duration_seconds),
                SUM(key_presses),
                SUM(mouse_clicks),
                SUM(mouse_distance_px),
                is_locked
            FROM window_activities
            WHERE start_time < ?
            GROUP BY date(start_time), app_id, is_locked
            ON CONFLICT(date, app_id, is_locked) DO UPDATE SET
                total_duration_seconds = excluded.total_duration_seconds,
                total_key_presses = excluded.total_key_presses,
                total_mouse_clicks = excluded.total_mouse_clicks,
                total_mouse_distance_px = excluded.total_mouse_distance_px;
        """, (cutoff_timestamp,))

        # 2. 物理修剪过期明细
        conn.execute("""
            DELETE FROM window_activities
            WHERE start_time < ?;
        """, (cutoff_timestamp,))

    # 3. 事务外执行轻量页面整理
    conn.execute("PRAGMA optimize;")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
```

---

## 4. 读查询透明路由层 (Query Compatibility)

### 4.1 查询路由策略
当用户调用 `timetrack report --date <YYYY-MM-DD>` 或 `timetrack today` 时：
1. **目标日期在 90 天内**：直接走现有 `window_activities`，提供 100% 完整窗口标题明细与秒级时间线。
2. **目标日期在 90 天前**：
   - 首先检查 `~/Documents/TimeReports/<YYYY-MM-DD>.md` 是否存在。如果存在，终端或导出直接复用历史 Markdown（此时依然保留原始窗口明细）。
   - 如果 Markdown 文件丢失且需要从数据库重构：从 `daily_activity_summary` 获取当日应用总时长、分类分布与键鼠指标，窗口标题显示为 `[历史已归档汇总]`。

---

## 5. 预期量化指标

* **明细表行数**：上限严格固定为 `90 天 * ~300 行/天 ≈ 27,000 行`。
* **聚合表行数**：每年约 `365 天 * 15 应用 ≈ 5,475 行`；10 年仅约 5.5 万行。
* **数据库体积**：
  * 明细表：~6 MB
  * 聚合表：~3 MB
  * 索引与系统开销：~3 MB
  * **10 年运行总库容稳定保持在 12~15 MB 以内**。
