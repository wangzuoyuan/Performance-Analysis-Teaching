# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 快速命令

跨平台启动器在 `run.py`，所有 `.sh / .command / .bat` 双击入口都委托给它。

```bash
# 一键启动后端 8000 + 前端 3000
python run.py start
# 重启（启动器检测到端口占用会跳过，必须先停）
python run.py stop && python run.py start
# 完全重置（清空 ~/.exam-tracker/；执行前会自动快照到 ~/.exam-tracker-backups）
python run.py init
# 数据备份 / 恢复（备份目录在 DATA_DIR 之外，不被 init 清空）
python run.py backup
python run.py restore [备份文件名]   # 省略则用最新一份

# 后端（带 reload，单独开发用）
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && npm run dev          # localhost:3000
npx tsc --noEmit                    # 类型检查
npm run build                       # 生产构建

# 后端测试
cd backend && source .venv/bin/activate && pytest tests/
pytest tests/test_excel_parser.py::test_xxx  # 单个用例

# 日志
tail -f ~/.exam-tracker/backend.log
tail -f ~/.exam-tracker/frontend.log
```

## 架构概览

**后端**：FastAPI + SQLite（`~/.exam-tracker/db.sqlite`），通过 SQLAlchemy 访问。三个路由模块挂载在 `/api` 前缀下：`ingest`（上传）/ `analysis`（查询）/ `chat`（SSE 流式对话）。

**前端**：Next.js 14 App Router + shadcn/ui + Recharts + Tailwind。全局布局由 `Shell.tsx`（侧边栏 + Topbar）管理，`ChatDrawer` 在 `layout.tsx` 全局挂载。页面：`/`(仪表盘，含「本周关注」「数据备份」卡) `/upload` `/compare` `/exam` `/student`（学生页含作业卡片、成长/谈话档案、「导出家长会一页纸」入口）`/student/[id]/report`(打印友好一页纸) `/homework`(作业，含 `/manage` `/warnings` `/correlation` `/settings` 子页)。

**数据库**：成绩相关 6 张表——`teacher`、`exam`、`upload`、`subject_score`、`total_score`、`class_average`；另有 `analysis_config`（段位阈值，单行 id=1）。作业相关 4 张表（原 Flask「作业跟踪」合并而来）——`class_roster`（花名册，主键真实学号 `student_id`，含座号/性别/`excluded`）、`homework_record`、`special_record`、`homework_setting`。档案 1 张表——`student_note`（成长/谈话档案：category 谈话/观察/家访/家长沟通/奖惩、content、follow_up 跟进项）。作业与档案均按真实学号 `student_id` 与成绩表关联。

**教学版新增**（核心）：`teaching_class`（grade+label+subject+kind，唯一键 `(grade,label)`；label 为字符串，高一数字班与高二/三走班名 `物A1`/`史B3` 一视同仁）、`teaching_class_member`（teaching_class_id ↔ 真实学号，含来源 `source`=class_num/parser/manual/roster）。**跨学年身份**：`student_identity`（人）、`student_alias`（学号↔人；分班后学号变更时靠姓名确认/对照表人工建链）。`subject_score`/`class_average`/`class_roster` 各增 `class_label`（教学班标签，可空）；`teacher` 增 `current_teaching_class_id`。旧单班字段 `teacher.target_class_highN` 保留列以兼容旧库但读侧不再使用。启动时 `db/migrate_teaching.py` 幂等建表+补列+把旧 `target_class_highN` 回填为一个行政教学班（仅首次、且尚无任何教学班时）。

## 部署（Docker / 群晖 NAS）

同一套代码既能本地 `run.py` 跑，也能 Docker 部署（不再维护单独副本）。部署文件：根 `docker-compose.yml`（backend + frontend + caddy 三服务，项目名 `grade_tracker`）、`Caddyfile`（`:8080` 路径分流 /api→backend、/→frontend）、`backend/Dockerfile`、`frontend/Dockerfile`（Next standalone）、`DEPLOY.md`（群晖 NAS 完整手册）。

部署特性**对本地开发无感（默认关闭）**：

- **登录鉴权**：`backend/app/auth.py` + `auth_router.py` + 前端 `AuthGate.tsx`。仅当设了 `APP_PASSWORD` **且**请求 Host 命中 `PUBLIC_HOST`（外网域名入口）时要求会话；内网 IP / 本地 dev / 未设密码一律放行。中间件挂在 `main.py`，放行 `/api/login`、`/api/logout`、`/api/auth/status`、`/api/health`。
- **数据目录**：`backend/app/paths.py` 的 `DATA_DIR`/`BACKUP_DIR` 读环境变量 `EXAM_TRACKER_DIR`/`EXAM_TRACKER_BACKUP_DIR`，缺省回落 `~/.exam-tracker`；Docker 镜像内设为 `/data` 挂卷。所有原先硬编码 `~/.exam-tracker` 的地方都改走 `paths.py`。
- **前端**：`next.config.js` 用 `output:'standalone'`；ChatDrawer 聊天地址生产走同源 `/api`（经 Caddy）、本地 dev 直连 `:8000`（跟随当前主机名，便于手机同 WiFi 访问）。
- **CORS**：`main.py` 默认放行 `http://<任意主机>:3000`（局域网 dev）+ 可选 `CORS_ORIGINS`；生产同源无需 CORS。

改部署后让 NAS 生效见 `DEPLOY.md`；NAS 上 compose 命令需带 `-p grade_tracker`（目录名含中文，裸跑会误建名为 `docker` 的平行栈）。

## API 端点一览

### ingest router
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传 Excel，返回解析结果 + 候选班号 |
| GET  | `/api/uploads` | 上传历史 |

### analysis router
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/exams` | 考试列表，支持 `?grade=` 筛选 |
| DELETE | `/api/exams/{id}` | 删除考试及所有关联数据（级联） |
| GET  | `/api/exams/{id}` | 考试详情：含 `students[]`、`rank_bands`、`rank_distribution`、`class_averages`、`stats` |
| GET  | `/api/focus-list/{id}` | 重点关注名单（临界段/薄弱段/严重偏科），支持 `?class_num=` |
| GET  | `/api/students/{id}` | 学生跨学年画像：含 `main_total_trend`（每项含 `class_rank`）、`five_trend`、`plus3_trend`、`san3_trend`、`subject_trend` |
| GET  | `/api/class/compare` | 班级横向对比，支持 `?exam_id=` |
| GET  | `/api/subject-weakness/{id}` | 单科薄弱名单，支持 `?class_num=` |
| GET  | `/api/band-trend` | 历次考试三段（高分/临界/薄弱）人数趋势，支持 `?grade=&class_num=` |
| GET  | `/api/rank-metrics` | 返回可选排名指标，支持 `?grade=&mode=range\|frequency` |
| GET  | `/api/rank-range` | 按指标和年级排名区间筛选学生 |
| GET  | `/api/rank-frequency` | 多场考试各排名区间频次统计 |
| GET  | `/api/analysis-config` | 读取段位阈值 |
| PUT  | `/api/analysis-config` | 保存段位阈值 |

> **教学版**：`/exams/{id}`、`/focus-list/{id}`、`/subject-weakness/{id}`、`/band-trend`、`/students/{id}`、`/rank-range`、`/rank-frequency` 均新增可选 `?teaching_class_id=` 查询参数（按教学班成员集合过滤，缺省=全年级）；返回项附带 `class_label`，`rank_bands` 按 `class_label` 分组并标 `mine`，`/class/compare` 返回 `dimension`/`mine_labels`/`source(class_average|computed)`。另新增 `GET /api/students?teaching_class_id=&grade=&q=`（学生检索，按身份去重）与 `GET /api/dashboard/overview?grade=`（总览聚合，每教学班一行）。

### teaching router（`/api/teaching`，`teaching/router.py`）— 教学版核心
| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/classes` | 列出（`?grade=`，带 `member_count`）/ 新建教学班 `{grade,label,subject?,kind,note?,sort_order?}` |
| PUT/DELETE | `/classes/{id}` | 改标签/学科/排序/备注 / 删班（连带成员） |
| GET/POST | `/classes/{id}/members` | 成员列表（学号/姓名/来源/行政班/状态）/ 加成员 `{student_ids?}` 或 `{names?}`（姓名走反查） |
| DELETE | `/classes/{id}/members/{student_id}` | 移除成员 |
| POST | `/classes/{id}/members/import` | 粘贴文本/学号批量导入，返回 `{matched, ambiguous, unmatched, added_count}` 四态 |
| POST | `/classes/{id}/sync-by-class-num` | 高一行政班：按 `int(label)` 从成绩表重算成员 |
| GET | `/candidate-classes?grade=` | 扫出可选行政班号 + 教学班标签（建班向导用） |
| GET/PATCH | `/current` | 读/设 `teacher.current_teaching_class_id`（当前班） |
| GET / `/name-candidates` | `/name-candidates?name=&grade=` | 按姓名找候选人（附行政班/最近名次，消歧用） |
| POST/DELETE | `/link` / `/alias/{student_id}` | 跨学年身份建链 / 解除链接 |
| POST | `/import-crosswalk` | 导入「学号↔学号」对照表批量建链 |
| GET | `/identity/{student_id}` | 某学号对应的全部学号集合（学段履历） |

### chat router
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | SSE 流式，支持 Anthropic 和 OpenAI 兼容两种 provider |
| GET  | `/api/chat/config` | 返回当前 LLM 配置（provider / model，不暴露 key） |

### homework router（`/api/homework`，`homework/router.py`）
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
| GET  | `/api/weekly-focus` | 本周关注名单：合并连续缺交预警 + 本周缺交激增 + 最近考试临界/薄弱/偏科 + 谈话跟进待办（缺交驱动，不依赖新考试） |

### notes router（`/api/notes`，`notes/router.py`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/notes/{student_id}` | 某生成长/谈话档案列表 |
| POST | `/api/notes` | 新增档案条目 |
| PUT  | `/api/notes/{id}` | 编辑 / 勾选跟进完成 |
| DELETE | `/api/notes/{id}` | 删除 |

### backup router（`/api/backup`，`backup/router.py`）
备份目录 `~/.exam-tracker-backups`（在 DATA_DIR 之外，不被 `init` 清空）。
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/backup` | 打包 db.sqlite + homework_exports 为时间戳 zip |
| GET  | `/api/backups` | 备份列表 |
| GET  | `/api/backup/{name}/download` | 下载备份 |
| POST | `/api/restore` | 恢复（先自动备份当前库，再覆盖，建议重启） |

## 对话工具集（20 个只读工具，`chat/tools.py`）

成绩 16 个：`list_exams` / `list_my_classes`（**教学版**：列出我的教学班，把「物A1班/1班」解析成 `teaching_class_id`） / `student_lookup` / `student_exam_detail` / `student_trend` / `student_learning_profile` / `class_trend` / `compare_classes` / `focus_list` / `subject_weakness` / `subject_progress_ranking` / `multi_exam_progress_ranking` / `band_trend` / `custom_rank_band_trend` / `rank_range_filter` / `rank_frequency_stat`

> **教学版**：`class_trend`/`compare_classes`/`focus_list`/`subject_weakness`/`multi_exam_progress_ranking`/`band_trend`/`custom_rank_band_trend`/`rank_range_filter`/`rank_frequency_stat` 均接受 `teaching_class_id`（或 `class_label`）按教学班过滤；`session.py` 系统提示含「多教学班」语义（未指定班=我教的班并集），业务口径（指标选择规则）原文保留。

作业 3 个：`student_homework_summary` / `class_homework_ranking` / `homework_grade_correlation`（支持 `subject`，总览附各科皮尔逊相关排序）

档案 1 个：`student_notes`（读取某生成长/谈话档案，结合成绩与缺交辅助起草谈话提纲/家长沟通稿）

新增工具：在 `tools.py` 里添加函数 + 注册到 `TOOL_FUNCTIONS` 字典和 `TOOLS` 列表，`session.py` 的 `execute_tool()` 自动调度。

## 数据流关键路径

**上传链路**：`ingest/router.py` → `filename_parser.py`（文件名解析年级/学期/考试类型）→ `excel_parser.py`（解析 Excel，高一固定列 vs 高二/三 3+3 两种 schema；教学版额外探测「教学班/走班/选科班」列表头，命中则逐行写 `class_label`）→ 写入 SQLite。教学版：`POST /api/teacher/bind-class`（旧单班绑定）**已废弃**，由 `/api/teaching/*` 配置流程取代；上传 `commit` 后返回 `detected_classes`（候选行政班号 + 教学班标签）供班级配置向导预填，并调 `teaching/service.sync_members_after_upload` 自动维护教学班成员。

**读端链路**：`analysis/router.py` 直接用 SQLAlchemy 查询，**没有使用** `analysis/trends.py` / `class_compare.py` / `focus_list.py` / `cross_year.py`（它们是早期抽象，router 内联了逻辑）。改查询逻辑只需改 `router.py`。

**段位阈值**：所有段位计算（`rank_bands`、`focus-list`、`band-trend`、AI 工具）必须调用 `analysis/config.py` 的 `get_band_config()`，不能硬编码默认值。用户在前端修改后，页面展示与 AI 问答口径同步。

**作业模块**：聚合查询集中在 `homework/service.py`（看板/排行/预警/相关性/`weekly_focus`），被 `homework/router.py` 与 `chat/tools.py` 共用；学科归类与录入文本解析在 `homework/parser.py`；Excel 导出在 `homework/export.py`。缺交看板默认口径：过滤 `remark` 非空（请假当天不算缺交）、`subject='全科'`、`excluded=1` 学生。一次性数据迁移脚本 `homework/migrate.py`（按姓名把旧 `homework.db` 的座号映射到成绩库真实学号，幂等可重跑）。

**档案 / 主动提醒 / 备份**：`notes/router.py` 管理 `student_note`（成长/谈话档案），AI 工具 `student_notes` 可读取。`homework/service.weekly_focus()` 合成「本周关注」，复用 `warnings` 与 `chat/tools.focus_list`（懒导入避免循环）。`backup/router.py` 与 `run.py` 的 `backup/restore` 子命令共用同一备份目录 `~/.exam-tracker-backups`；`run.py init` 清空前自动快照。

## 业务口径（指标选择规则）

这些规则写在 `chat/session.py` 系统提示，直接影响 AI 回答质量，修改工具返回值时需保持一致：

- **跨学年趋势**：只能用主三门和语数英原始分；禁止跨高一→高二用九门或 +3 比较
- **总分趋势**：用 `xueji_rank`（学籍排名）；无学籍排名时用 `grade_percentile`
- **高一单科 / 高二高三语数英**：用 `grade_percentile`（百分位降低 = 进步）
- **高二高三 +3 选考单科**：用 `grade_score`（等级分）；等级分精确值为 70/67/64/61/58/55/52/49/46/43/40
- `raw_score` 只用于单点描述（"该次原始分为X"），不得用于趋势计算

## 前端开发要点

- **新增页面**：不要加 `<header>` / `max-w-*` / `min-h-screen` / `bg-slate-50`，`Shell.tsx` 已接管布局。
- **shadcn 组件**：`npx shadcn@latest add <name>`（包名是 `shadcn`，不是 `shadcn-ui`）。
- **颜色 token**：统一用 `tailwind.config.js` 的 `brand-*` / `success` / `warning` / `danger`；Recharts 内直接写字符串（不接受 CSS 变量）。
- **ChatDrawer 触发**：`window.dispatchEvent(new Event('open-chat'))`，不要直接 import/ref。
- **缺考字段**：API 返回 `null`，前端一律显示 `"—"`，不要显示 `0`。
- **移动端适配**：`Shell.tsx` 已响应式（侧栏收为汉堡菜单、内容区窄屏减边距）。窄屏别写死宽度，用 `w-full sm:w-[..]` + `flex-col sm:flex-row`；超宽数据表（考试成绩矩阵）保留桌面宽表（`hidden md:block`）的同时配一份卡片视图（`md:hidden`，如 `StudentScoreMobileCards`）；多页签用 `overflow-x-auto` 横滑而非换行。`layout.tsx` 已声明 `viewport`，对话输入框用 `text-base`(16px) 防 iOS 聚焦缩放。

## 对话助手配置（`backend/.env`）

```env
# Anthropic（默认）
CHAT_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_BASE_URL=          # 留空用官方；填兼容地址可切换第三方
ANTHROPIC_MODEL=claude-sonnet-4-6

# OpenAI 兼容
CHAT_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=             # 留空用 api.openai.com；填 /v1 结尾的兼容地址
OPENAI_MODEL=gpt-4o-mini
```

## 测试覆盖

有测试：`api` / `chat_config` / `chat_tools` / `db` / `excel_parser` / `filename_parser` / `homework_parser`（学科解析）/ `homework_router`（看板/相关性/花名册/学期端点 + 皮尔逊单测）/ `notes_router`（档案增删改 + 跟进）/ `backup_weekly`（备份/恢复/本周关注）

**无测试**：`analysis/router.py` 的计算逻辑（`trends` / `class_compare` / `focus_list` / `cross_year` / `rank_metrics` 模块同样无测试）。
