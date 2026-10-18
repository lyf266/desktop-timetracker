# 📋 Desktop TimeTracker 待办与功能路线图 (TODO & Backlog)

> **核心原则**：恪守“100% 纯本地、零外部依赖、零明文痕迹、绝对隐私优先”的产品底线。

---

## 🎯 待办需求：本地零留痕键盘与鼠标输入活力指数 (Input Activity Tracker)

- **任务状态**：`[ ] 规划中 (Backlog)`
- **建议排期**：考后恢复期 (2026-10-25 起，战时备考期间全面封板)
- **优先级**：P2 (高价值工程扩展)

### 1. 需求背景与目标
现有的 `desktop-timetracker` 已经实现了极高精度的“窗口聚焦时长”与“空闲/锁屏状态检测”，但缺乏对“实际操作强度（编码密度、打字活跃度）”的量化指标。
通过引入**底层硬件输入盲计数器**，在**不记录任何具体按键内容、不记录轨迹坐标**的前提下，评估真实心流状态（如深思阅读 vs 高频敲码），作为活力指数与专注纯度的重要参考。

---

### 2. 核心架构契约与四大硬约束 (Non-Negotiable Invariants)

1. **盲输入丢弃模型 (Blind Counter Invariant)**：
   - 监听 Linux 底层 `/dev/input/event*`（基于 `evdev`）。
   - 事件触发时，**立即丢弃 `event.code`（按键名称/扫描码）**，仅做全局整数自增：`total_keystrokes += 1`。
   - 严禁在内存变量、日志或数据库中出现任何特定键位（如字母、数字、回车等）的识别与映射，对密码与聊天内容完全不可逆。

2. **抗击键节奏分析 (Anti-timing Attack / 粗粒度分桶)**：
   - **严禁记录毫秒级击键间隔时间戳**（杜绝根据打字节奏逆向推断密码或输入习惯）。
   - 仅以粗粒度时间窗口（与现有的 5 秒采样或分钟级窗口切片绑定）聚合为一个纯标量总数：如 `keys_count: 142`。

3. **鼠标轨迹脱敏 (位移标量 + 点击频次)**：
   - **绝不记录绝对屏幕坐标**（$(x, y)$）或点击热区。
   - 仅对移动增量累加欧氏距离标量：$\Delta d = \sqrt{\Delta x^2 + \Delta y^2}$。
   - 仅统计鼠标按键（左键、右键、中键）按下总次数。

4. **100% 纯本地物理隔离**：
   - 扩展字段直接落入本地 `~/.local/share/timetracker/timetracker.db`。
   - 零网络请求、零外部 telemetry、零日志落盘。

---

### 3. 实现路线图与落地检查清单 (Checklist)

- [ ] **权限与设备识别**：
  - [ ] 探查当前系统的键盘与鼠标输入事件设备节点（`/dev/input/by-id/*` 或自动遍历 `event*`）。
  - [ ] 配置免 root 用户空间方案（文档明确添加 `input` 组，或提供配套极简 udev 规则）。
- [ ] **输入采集守护线程 (`InputActivityCollector`)**：
  - [ ] 在 `src/desktop-timetracker` 内部启动独立轻量后台线程，低 CPU 轮询/阻塞读取事件。
  - [ ] 实现滑动窗口缓冲区，在每次窗口切换或落库事件发生时原子读取并重置计数器。
- [ ] **SQLite 数据库表结构轻量平滑迁移**：
  - [ ] 在 `window_activities` 增加 `key_presses` (INTEGER DEFAULT 0)、`mouse_clicks` (INTEGER DEFAULT 0)、`mouse_distance_px` (INTEGER DEFAULT 0)。
  - [ ] 确保老旧数据库启动时自动执行 `ALTER TABLE ADD COLUMN` 兼容迁移，不破坏历史数据。
- [ ] **报表输出与指标可视化 (CLI)**：
  - [ ] 在 `timetrack today` 与 `timetrack report` 中输出活跃度摘要（如：总击键量、鼠标移动里程、平均 APM / 敲击热度）。
  - [ ] 在 Markdown 日报模板中呈现“时间投入 vs 击键产出”矩阵。
- [ ] **单元测试与安全合规断言**：
  - [ ] 增加针对敏感字符输入的专项验证测试，断言日志与数据库中绝无任何 keycode/字符残留。
