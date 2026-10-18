# 📋 Desktop TimeTracker 待办与功能路线图 (TODO & Backlog)

> **核心原则**：恪守“100% 纯本地、零外部依赖、零明文痕迹、绝对隐私优先”的产品底线。

---

## 🎯 待办需求：本地零留痕键盘与鼠标输入活力指数 (Input Activity Tracker)

- **任务状态**：`[x] 已完成 (Delivered)`
- **完成日期**：2026-10-18
- **优先级**：P2 (高价值工程扩展)

### 1. 需求背景与目标
现有的 `desktop-timetracker` 已经实现了极高精度的“窗口聚焦时长”与“空闲/锁屏状态检测”，但缺乏对“实际操作强度（编码密度、打字活跃度）”的量化指标。
通过引入**底层硬件输入盲计数器**，在**不记录任何具体按键内容、不记录轨迹坐标**的前提下，评估真实心流状态（如深思阅读 vs 高频敲码），作为活力指数与专注纯度的重要参考。

---

### 2. 核心架构契约与四大硬约束 (Non-Negotiable Invariants)

1. **盲输入丢弃模型 (Blind Counter Invariant)**：
   - 监听 Linux 底层 `/dev/input/event*`（基于纯标准库 `struct` / `selectors` 实现）。
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

- [x] **权限与设备识别**：
  - [x] 自动探测 `/proc/bus/input/devices` 中的键盘与鼠标输入事件设备节点（精准过滤电源键、视频总线与蜂鸣器）。
  - [x] 配置免 root 用户空间方案与平滑降级（`install.sh` 检测并引导 `sudo usermod -aG input $USER`，守护进程无权限时平滑回退并不崩溃）。
- [x] **输入采集守护线程 (`InputActivityMonitor`)**：
  - [x] 在 `src/desktop-timetracker` 内部启动独立轻量后台线程，非阻塞读取事件与动态设备热插拔重扫。
  - [x] 实现线程安全原子缓冲区，在窗口切换、整点跨越及落库时原子读取并重置计数器。
- [x] **SQLite 数据库表结构轻量平滑迁移**：
  - [x] 在 `window_activities` 增加 `key_presses` (INTEGER DEFAULT 0)、`mouse_clicks` (INTEGER DEFAULT 0)、`mouse_distance_px` (INTEGER DEFAULT 0)。
  - [x] 老旧数据库启动时自动执行 `ALTER TABLE ADD COLUMN` 兼容迁移，不破坏历史数据。
- [x] **报表输出与指标可视化 (CLI)**：
  - [x] 在 `timetrack today` 概览中输出全天总击键数、平均击键率（KPM）、鼠标滑动距离（自动换算米/厘米/公里）及点击次数。
  - [x] 扩展 24 小时活跃时段表格为「综合时段矩阵」，按小时展示各时段专注时长、打字量、鼠标滑行距离与进度条。
  - [x] 在 Markdown 日报模板与导出文件中呈现完整的键鼠投入指标与 24 小时时段表。
- [x] **单元测试与安全合规断言**：
  - [x] 编写 `tests/test_input_tracker.py` 自动化测试套件（13 个针对性测试全部通过），包含针对绝对盲计数与零留痕的断言验证。
