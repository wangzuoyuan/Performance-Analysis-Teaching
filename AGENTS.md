# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

> 本文件是 webapp 目录的补充说明。父目录 AGENTS.md（`../AGENTS.md`）含架构总览和业务口径，两者都会加载，本文件只记录 webapp 特有细节和对父文件的修正。

## 快速命令

跨平台启动器在 `run.py`，所有 `.sh / .command / .bat` 双击入口都委托给它。日常开发优先用 `python3 run.py <子命令>`；如果目标机器有 `python` 命令，也可等价使用 `python run.py <子命令>`。

```bash
# 一键启动后端 8000 + 前端 3000（跨平台）
python3 run.py start
./start.sh                       # macOS 命令行等价

# 重启（改代码后必须先停，启动器检测到端口占用会跳过启动）
python3 run.py stop && python3 run.py start

# 完全重置（清空 ~/.exam-tracker/，Windows 上是 %USERPROFILE%\.exam-tracker\）
python3 run.py init

# 后端（带 reload，单独开发用）
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm run dev          # localhost:3000
npx tsc --noEmit                    # 类型检查
npm run build                       # 生产构建（CI 没配，靠这个兜底）

# 后端测试
cd backend && source .venv/bin/activate && pip install pytest && pytest tests/
pytest tests/test_excel_parser.py::test_xxx  # 单个用例

# 日志
tail -f ~/.exam-tracker/backend.log
tail -f ~/.exam-tracker/frontend.log
```

## 部署（Docker / 群晖 NAS）

同一套代码既能本地 `run.py` 跑，也能 Docker 部署。部署文件：根 `docker-compose.yml`（backend + frontend + caddy，项目名 `grade_tracker`）、`Caddyfile`（`:8080` 路径分流）、`backend/Dockerfile`、`frontend/Dockerfile`（Next standalone）、`DEPLOY.md`（NAS 手册）。部署特性**对本地开发无感、默认关闭**：

- **登录鉴权**（`backend/app/auth.py` + `auth_router.py` + 前端 `AuthGate.tsx`）：仅当设了 `APP_PASSWORD` 且 Host 命中 `PUBLIC_HOST` 时要求登录；内网 / 本地 dev / 未设密码放行。中间件在 `main.py`。
- **数据目录**：`backend/app/paths.py` 的 `DATA_DIR`/`BACKUP_DIR` 读 `EXAM_TRACKER_DIR`/`EXAM_TRACKER_BACKUP_DIR`，缺省回落 `~/.exam-tracker`；Docker 内为 `/data`。
- 前端 `next.config.js` 用 `output:'standalone'`；ChatDrawer 生产走同源 `/api`、dev 直连 `:8000`。CORS 默认放行 `:3000` 局域网 + 可选 `CORS_ORIGINS`。
- NAS 上 compose 命令需带 `-p grade_tracker`（目录名含中文，裸跑会误建平行栈）。

## API 端点一览

### ingest router（`/api`）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传 Excel，返回解析结果 + 候选班号 |
| GET  | `/api/uploads` | 上传历史 |

### analysis router（`/api`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/exams` | 考试列表，支持 `?grade=` 筛选 |
| DELETE | `/api/exams/{id}` | 删除考试及所有关联数据（级联） |
| GET  | `/api/exams/{id}` | 考试详情：含 `students[]`、`rank_bands`、`rank_distribution`、`class_averages`、`stats` |
| GET  | `/api/focus-list/{id}` | 重点关注名单（临界段/薄弱段/严重偏科），支持 `?class_num=` |
| GET  | `/api/students/{id}` | 学生跨学年画像：含 `main_total_trend`（每项含 `class_rank`）、`five_trend`、`plus3_trend`、`san3_trend`、`subject_trend` |
| GET  | `/api/class/compare` | 班级横向对比，支持 `?exam_id=` |
| GET  | `/api/subject-weakness/{id}` | 单科薄弱名单，支持 `?class_num=` |
| GET  | `/api/band-trend` | 历次考试高分段/临界段/薄弱段人数趋势，支持 `?grade=&class_num=` |
| GET  | `/api/rank-metrics` | 返回排名筛选/频次统计可用指标，支持 `?grade=&mode=range\|frequency` |
| GET  | `/api/rank-range` | 单次考试按指标和年级排名区间筛选学生 |
| GET  | `/api/rank-frequency` | 多场考试排名区间/百分位区间/精确等级分频次统计 |
| GET  | `/api/analysis-config` | 读取段位阈值配置 |
| PUT  | `/api/analysis-config` | 保存段位阈值配置 |

### chat router（`/api`）
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | SSE 流式，支持 Anthropic 和 OpenAI 兼容两种 provider |
| GET  | `/api/chat/config` | 返回当前 LLM 配置（provider / model，不暴露 key） |

### homework router（`/api/homework`，`homework/router.py`）
由原独立 Flask「作业跟踪」合并而来，数据并入同一 SQLite 库。
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/records` `/special-records` | 智能文本录入缺交 / 特殊记录（by_student / by_subject 两模式），录入后自动导出当天 Excel |
| GET  | `/kpi` `/trend` `/subjects` `/rankings` `/warnings` | 看板统计；`warnings` 为连续缺交预警（连续 2 次黄、≥3 次红） |
| GET  | `/correlation` | 缺交 × 成绩相关：默认总缺交 × 主三门排名；`?subject=` 切到该科缺交 × 该科年级百分位 |
| GET  | `/correlation/subjects` | 各科「缺交拖成绩」皮尔逊相关系数排序 |
| GET  | `/student/{student_id}` | 单个学生作业概况（供学生画像页作业卡片） |
| GET/PUT/DELETE | `/manage/records[/{id}]` | 记录管理；列表支持 `?date=&student=&subject=` 筛选（供看板图表下钻） |
| GET/POST/DELETE/PUT | `/roster[/{student_id}[/toggle-excluded]]` | 花名册增删查 + 排除统计开关 |
| GET/PUT | `/semester` | 学期起止与名称配置 |
| GET  | `/api/weekly-focus` | 本周关注：连续缺交预警 + 本周缺交激增 + 最近考试临界/薄弱/偏科 + 谈话跟进待办（缺交驱动，不依赖新考试） |

### notes / backup router
- `notes/router.py`（`/api/notes`）：`GET /{student_id}`、`POST`、`PUT /{id}`（含跟进勾选）、`DELETE /{id}`，管理 `student_note` 成长/谈话档案。
- `backup/router.py`（`/api/backup`）：`POST /backup`、`GET /backups`、`GET /backup/{name}/download`、`POST /restore`。备份目录 `~/.exam-tracker-backups`（在 DATA_DIR 之外）。

## 对话工具集（19 个只读工具，`chat/tools.py`）

成绩 15 个：`list_exams` / `student_lookup` / `student_exam_detail` / `student_trend` / `student_learning_profile` / `class_trend` / `compare_classes` / `focus_list` / `subject_weakness` / `subject_progress_ranking` / `multi_exam_progress_ranking` / `band_trend` / `custom_rank_band_trend` / `rank_range_filter` / `rank_frequency_stat`

作业 3 个：`student_homework_summary` / `class_homework_ranking` / `homework_grade_correlation`（支持 `subject` 参数，总览模式附各科皮尔逊相关排序）

档案 1 个：`student_notes`（读取某生成长/谈话档案，结合成绩与缺交辅助起草谈话/家长沟通）

新增工具只需在 `tools.py` 里添加函数并注册到 `TOOL_FUNCTIONS` 字典和 `TOOLS` 列表，`session.py` 自动调度。

## 数据流关键路径

**上传链路**：`ingest/router.py` → `filename_parser.py`（文件名解析年级/学期/考试类型）→ `excel_parser.py`（解析 Excel，高一固定列 vs 高二/三 3+3 两种 schema）→ 写入 6 张 SQLite 表。首次上传后弹窗确认班号 → `POST /api/teacher/bind-class`。

**读端链路**：`analysis/router.py` 直接用 SQLAlchemy 查询，**没有使用** `analysis/trends.py` / `class_compare.py` / `focus_list.py` / `cross_year.py` 这些计算模块（它们是早期抽象，当前 router 内联了逻辑）。改查询逻辑只需改 `router.py`。

**学生画像单科趋势**：`/api/students/{id}` 的 `subject_trend` 只返回 `raw_score` 或 `grade_score` 有真实值的单科记录。像 2025 年 9 月只有语数英时，物化生政史地即使原始导入行残留百分位，也不能进入单科趋势线；前端明细表仍显示为 `"—"`。

**段位阈值**：所有段位计算（考试详情、focus-list、band-trend、AI 工具）都应调用 `analysis/config.py` 的 `get_band_config()`，不要硬编码默认阈值。用户在前端改段位后，页面和 AI 问答口径必须同步。

**作业模块**：聚合查询集中在 `homework/service.py`（看板/排行/预警/相关性/`weekly_focus`），被 `homework/router.py` 与 `chat/tools.py` 共用；学科归类与录入文本解析在 `homework/parser.py`；Excel 导出在 `homework/export.py`。新增 4 张表 `class_roster`/`homework_record`/`special_record`/`homework_setting`，作业记录按真实学号 `student_id` 与成绩表关联。缺交看板默认口径：过滤 `remark` 非空（请假当天不算缺交）、`subject='全科'`、`excluded=1` 学生。一次性迁移脚本 `homework/migrate.py`（按姓名把旧 `homework.db` 座号映射到成绩库真实学号，幂等可重跑）。

**档案 / 主动提醒 / 备份**：`student_note` 表 + `notes/router.py` 管理成长/谈话档案，AI 工具 `student_notes` 可读取。`weekly_focus()` 合成「本周关注」（懒导入 `chat/tools.focus_list` 避免循环依赖）。`backup/router.py` 与 `run.py` 的 `backup/restore` 子命令共用备份目录 `~/.exam-tracker-backups`（DATA_DIR 之外）；`run.py init` 清空前自动快照。打印一页纸 `/student/[id]/report` 靠 `@media print`（`print:hidden` 隐藏侧栏/顶栏）。

## 业务口径（AI 与趋势指标）

- **加三学科**：指物理、化学、生物、政治、历史、地理六科的统称；`+3/选考三科` 才表示高二/高三学生实际选择参加的三门。
- **跨学年趋势**：只能用主三门和语数英原始分；高一到高二禁止用九门或 +3 比。
- **总分趋势**：用 `xueji_rank`；无学籍排名时用 `grade_percentile`。
- **高一所有单科**：用 `grade_percentile`，百分位降低表示进步。
- **高二/高三语数英单科**：用 `grade_percentile`。
- **高二/高三加三选考单科**：用 `grade_score`，不用原始分和百分位判断趋势；等级分按 70、67、64、61、58、55、52、49、46、43、40 精确值统计。
- `raw_score` 只用于单次考试原始分描述，不得用于趋势进退步计算。

## 前端开发要点

- **新增页面**：不要加 `<header>` / `max-w-*` / `min-h-screen` / `bg-slate-50`，`Shell.tsx` 已接管布局。
- **shadcn 组件**：`npx shadcn@latest add <name>`（包名是 `shadcn`，不是 `shadcn-ui`）。
- **颜色 token**：统一用 tailwind.config.js 的 `brand-*` / `success` / `warning` / `danger`；Recharts 内直接写字符串（它不接受 CSS 变量）。
- **ChatDrawer 触发**：通过 `window.dispatchEvent(new Event('open-chat'))` 打开，不要直接 import/ref。
- **缺考字段**：API 返回 `null`，前端一律显示 `"—"`，不要显示 `0`。
- **单科趋势线**：只使用真实有单科分数的点。前端已有 `hasSubjectScore()` 防线，避免 `raw_score=null` 的记录进入小卡片趋势线。
- **移动端适配**：`Shell.tsx` 已响应式（侧栏收为汉堡菜单、内容区窄屏减边距）。窄屏别写死宽度，用 `w-full sm:w-[..]` + `flex-col sm:flex-row`；超宽数据表（考试成绩矩阵）保留桌面宽表（`hidden md:block`）的同时配一份卡片视图（`md:hidden`，如 `StudentScoreMobileCards`）；多页签用 `overflow-x-auto` 横滑而非换行。`layout.tsx` 已声明 `viewport`，对话输入框用 `text-base`(16px) 防 iOS 聚焦缩放。

## 对话助手配置（`backend/.env`）

```env
# Anthropic（默认）
CHAT_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=          # 留空用官方；填兼容地址可切换第三方
ANTHROPIC_MODEL=Codex-sonnet-4-6

# OpenAI 兼容
CHAT_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=             # 留空用 api.openai.com；填 /v1 结尾的兼容地址
OPENAI_MODEL=gpt-4o-mini
```

## 测试覆盖

有测试：`api` / `chat_config` / `chat_tools` / `db` / `excel_parser` / `filename_parser` / `homework_parser` / `homework_router` / `notes_router` / `backup_weekly`

**无测试**：`analysis/router.py` 的计算逻辑（trends / class_compare / focus_list / cross_year 模块同样无测试）。
