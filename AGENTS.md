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
npm run build                       # 生产构建（CI 同样执行）

# 后端测试
cd backend && source .venv/bin/activate && pip install pytest && pytest tests/
pytest tests/test_excel_parser.py::test_xxx  # 单个用例

# 日志
tail -f ~/.exam-tracker/backend.log
tail -f ~/.exam-tracker/frontend.log
```

## 部署（Docker / 群晖 NAS）

同一套代码既能本地 `run.py` 跑，也能 Docker 部署。部署文件：根 `docker-compose.yml`（backend + frontend + caddy，项目名 `grade_tracker`）、`compose.env.example`（GHCR 镜像与版本）、`Caddyfile`、两个 Dockerfile、`DEPLOY.md`。`.github/workflows/docker.yml` 发布 amd64/arm64 镜像；Compose 默认拉 GHCR，`--build` 时仍使用本地源码。部署特性**对本地开发无感、默认关闭**：

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
| GET  | `/api/focus-list/{id}` | 当前学科临界/薄弱名单，支持 `?teaching_class_id=` |
| GET  | `/api/students/{id}` | 当前学科跨学年画像，合法无成绩成员返回空 `series` |
| GET  | `/api/class/compare` | 当前学科教学班横向对比，支持 `?exam_id=` |
| GET  | `/api/subject-weakness/{id}` | 当前学科薄弱名单，支持 `?teaching_class_id=` |
| GET  | `/api/band-trend` | 当前学科历次段位人数趋势，支持 `?grade=&teaching_class_id=` |
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
| POST | `/records` `/special-records` | 智能文本录入缺交 / 特殊记录（by_student / by_subject 两模式；`by_subject` 为兼容旧名，当前含义是“按作业种类”）；显式 `teaching_class_id` 必须属于教师当前学科，录入后自动导出当天 Excel |
| GET  | `/dashboard` `/kpi` `/trend` `/subjects` `/rankings` `/warnings` | 看板统计；缺省范围仅为当前学科合法教学班成员并集，显式他科班返回 409；`/subjects` 为兼容旧路径，返回各作业种类分布；`warnings` 为同一作业种类连续缺交预警（连续 2 次黄、≥3 次红） |
| GET  | `/correlation` | 总缺交 × 当前学科班内排名；可用 `teaching_class_id` 限定合法教学班 |
| GET  | `/correlation/subjects` | 历史兼容路径，不得返回其他学科统计 |
| GET  | `/student/{student_id}` | 单个学生作业概况（供学生画像页作业卡片） |
| GET/PUT/DELETE | `/manage/records[/{id}]` | 记录管理；列表支持 `?date=&student=&subject=` 筛选（`subject` 为兼容参数名，实际筛作业种类，供看板图表下钻） |
| GET/POST/DELETE/PUT | `/roster[/{student_id}[/toggle-excluded]]` | 花名册增删查 + 排除统计开关 |
| GET/PUT | `/semester` | 学期起止与名称配置 |
| GET  | `/api/weekly-focus` | 当前学科范围的缺交预警、临界/薄弱与谈话跟进待办 |

前端首页渲染范围联动的作业摘要；`/homework` 页头必须保留 `ClassScopePicker`，且切班请求只允许最新响应写入，防止旧班数据覆盖当前班。`/api/teaching/classes` 只返回教师当前学科（兼容 `NULL`、空串或纯空白 subject 旧班）的教学班，遗留他科 current id 在读取时回退为 all。空 subject 旧班在菜单、默认并集、标签、提交率和显式范围中使用同一兼容语义；所有 teaching CRUD、作业记录/花名册按 ID 写入也必须先验证当前学科范围。花名册新增必须绑定具体合法教学班；若已有 member 但缺 roster，应复用原 student ID 补全，不得创建重复身份。删除共享到范围外教学班的学生必须拒绝，不能跨学科清成员关系。

### notes / backup router
- `notes/router.py`（`/api/notes`）：`GET /{student_id}`、`POST`、`PUT /{id}`（含跟进勾选）、`DELETE /{id}`，管理 `student_note` 成长/谈话档案。
- `backup/router.py`（`/api/backup`）：`POST /backup`、`GET /backups`、`GET /backup/{name}/download`、`POST /restore`。备份目录 `~/.exam-tracker-backups`（在 DATA_DIR 之外）。

## 对话工具集（19 个只读工具，`chat/tools.py`）

成绩 15 个：`list_exams` / `student_lookup` / `student_exam_detail` / `student_trend` / `student_learning_profile` / `class_trend` / `compare_classes` / `focus_list` / `subject_weakness` / `subject_progress_ranking` / `multi_exam_progress_ranking` / `band_trend` / `custom_rank_band_trend` / `rank_range_filter` / `rank_frequency_stat`

作业 3 个：`student_homework_summary` / `class_homework_ranking` / `homework_grade_correlation`（主口径为总缺交 × 排名；`subject` 参数和各科皮尔逊排序保留为历史兼容入口）

档案 1 个：`student_notes`（读取某生成长/谈话档案，结合成绩与缺交辅助起草谈话/家长沟通）

新增工具只需在 `tools.py` 里添加函数并注册到 `TOOL_FUNCTIONS` 字典和 `TOOLS` 列表，`session.py` 自动调度。

## 数据流关键路径

**上传链路**：`ingest/router.py`（`POST /api/uploads/preview` 取回按文件名识别的年级/学期/考试类型，前端逐文件确认后 `POST /api/uploads/commit` 入库）→ `filename_parser.py` → `excel_parser.py`（高一固定列 vs 高二/三 3+3 两种 schema；教学版额外探测「教学班/走班/选科班」列写 `class_label`）→ 写入 SQLite。教学版：旧的 `POST /api/teacher/bind-class`（单班绑定）已废弃、前端上传页的「绑定班级」步骤已移除；班级在 `/settings/classes`（`/api/teaching/*`）维护，`commit` 后由 `teaching/service.sync_members_after_upload` 自动维护教学班成员。

**读端链路**：`analysis/router.py` 与 `chat/tools.py` 直接按教师当前学科和教学班范围查询；早期 `trends.py` / `class_compare.py` / `focus_list.py` / `cross_year.py` 已删除。

**学生画像单科趋势**：`/api/students/{id}` 的 `subject_trend` 只返回 `raw_score` 或 `grade_score` 有真实值的单科记录。像 2025 年 9 月只有语数英时，物化生政史地即使原始导入行残留百分位，也不能进入单科趋势线；前端明细表仍显示为 `"—"`。

**段位阈值**：所有段位计算（考试详情、focus-list、band-trend、AI 工具）都应调用 `analysis/config.py` 的 `get_band_config()`，不要硬编码默认阈值。用户在前端改段位后，页面和 AI 问答口径必须同步。

**作业模块**：聚合查询集中在 `homework/service.py`（看板/排行/预警/相关性/`weekly_focus`），被 `homework/router.py` 与 `chat/tools.py` 共用；作业种类归类与录入文本解析在 `homework/parser.py`；Excel 导出在 `homework/export.py`。新增 4 张表 `class_roster`/`homework_record`/`special_record`/`homework_setting`，作业记录按真实学号 `student_id` 与成绩表关联。`HomeworkRecord.subject` / `?subject=` / `/subjects` 是兼容旧库和旧 API 的命名，当前业务含义均为“作业种类”。缺交看板默认口径：过滤 `remark` 非空（请假当天不算缺交）、`subject='全科'`、`excluded=1` 学生。智能录入支持混合写法（如 `张三校本优秀`、`订正缺交：李四、王五`、`校本差：吴六、赵七`），并按作业种类统计校本作业、周末作业、试卷订正、日常作业等。一次性数据迁移脚本 `homework/migrate.py`（按姓名把旧 `homework.db` 座号映射到成绩库真实学号，幂等可重跑）。

**档案 / 主动提醒 / 备份**：`student_note` 表 + `notes/router.py` 管理成长/谈话档案，AI 工具 `student_notes` 只在合法成员范围内读取。`weekly_focus()` 直接复用当前学科排名口径，不调用 chat focus 工具。备份目录为 `~/.exam-tracker-backups`（DATA_DIR 之外），`run.py init` 清空前自动快照。打印一页纸 `/student/[id]/report` 使用 `@media print`。

## 业务口径（AI 与趋势指标）

- **唯一学科**：所有页面、API、导出和 AI 工具只使用教师唯一任教学科。
- **教学班范围**：未选班时为当前学科所有合法教学班成员的去重并集；选班时 `teaching_class_id` 是不可覆盖的硬边界。
- **排名池**：各教学班独立 competition ranking，不合并班级排名池。
- **分数口径**：高二/高三选考科目使用 `grade_score`，其他情况使用 `raw_score`；无真实分数的合法成员保留但成绩/排名为 `null`。
- **旧总分**：`TotalScore` 只用于旧库启动、备份/恢复和整场删除兼容，不得进入业务读写。

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

有测试：`api` / `chat_config` / `chat_tools` / `db` / `excel_parser` / `filename_parser` / `homework_parser` / `homework_router` / `homework_dashboard` / `notes_router` / `backup_weekly` / `teaching_router` / `scope`

CI：`.github/workflows/ci.yml` 在 push 到 `main` 与所有 PR 上跑后端 `pytest` + 前端 `tsc --noEmit`/`next build`。

**无测试**：`analysis/router.py` 的计算逻辑（trends / class_compare / focus_list / cross_year 模块同样无测试）。
