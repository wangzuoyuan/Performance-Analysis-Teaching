# 成绩分析（教学版）

![version](https://img.shields.io/badge/version-2.0.0-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
[![CI](https://github.com/wangzuoyuan/Performance-Analysis-Teaching/actions/workflows/ci.yml/badge.svg)](https://github.com/wangzuoyuan/Performance-Analysis-Teaching/actions/workflows/ci.yml)

> 任课老师的多教学班、唯一任教学科成绩与教学质量分析 Web 应用。
> 一位老师任教**一个固定学科、多个教学班**（高一可为行政班，高二/三可为走班名），
> 所有分析只使用当前学科与合法教学班成员，并支持跨学年身份继承。

由「成绩分析（班主任版）」移植而来：把全系统「按班级」的口径从**单一数字行政班号**
升级为**老师可配置的多个教学班**（字符串标签 `class_label`）。架构与口径说明见
[CLAUDE.md](CLAUDE.md) 与 [AGENTS.md](AGENTS.md)。

本项目按 MIT License 开源，可自由使用、修改和二次分发。

---

## 功能特性

### 教学班（核心）
- **单学科多教学班模型**：教师首次配置唯一任教学科，并维护该学科下任意多个教学班。
- **班级配置向导**（`/settings/classes`）：按年级建班、维护成员、批量导入（学号/姓名/花名册）、按行政班号一键同步、排序删班、设当前班。
- **成员导入**：粘贴学号或姓名清单，返回匹配、同名待消歧与未匹配结果；候选信息只使用当前学科成绩辅助辨认。
- **两种仪表盘**：总览（跨我所有班聚合，学生旁标教学班）+ 分班（选定单班后的专属视图），顶栏一键切换。
- **跨学年学情继承**：分班导致学号变更时，以「姓名确认 + 学号对照表」人工建链，让跨学年画像/趋势/档案接续。

### 成绩分析
- **Excel 批量导入**：兼容旧多学科/总分工作簿，但只解析并持久化教师当前学科；自动识别教学班列写入 `class_label`。
- **单科双口径**：高二/高三选考科目使用 `grade_score`，其他情况使用 `raw_score`；总分仅保留旧库兼容，不进入业务分析。
- **考试详情页**：班级均分、学生成绩明细（带教学班徽章）、名次段分布（按教学班分组并高亮我的班）、排名频次、排名区间筛选、重点关注名单。
- **可自定义关注段位**：高分段/临界段/薄弱段区间可调，页面与 AI 口径同步。
- **历次段位趋势**、**排名筛选与频次统计**、**多场进退步趋势排行**。
- **班级对比页（D2）**：只比较当前学科下教师所教教学班；无官方均分时按合法成员现算并标「估算」。
- **学生画像页**：当前学科跨学年趋势、历次明细、教学班内排名、作业与学段履历；合法无成绩成员仍保留空画像。

### 作业 / 档案 / AI / 备份
- **作业跟踪**：面向任课老师的单学科场景，智能文本录入缺交/请假/迟到/评价，按作业种类（校本作业、周末作业、试卷订正、日常作业等）统计，看板（每日趋势/各类作业占比/排行/连续缺交预警）、自动导出 Excel、花名册排除开关、学期配置。**仅按姓名添加的教学班成员也能录缺交并计入看板**（占位学号按教学班隔离，同名跨班互不串数据）。
- **混合智能录入**：同一批文本可混写 `张三校本优秀`、`订正缺交：李四、王五`、`校本差：吴六、赵七`。
- **缺交 × 成绩相关性**：总缺交次数与当前学科班内排名散点，只覆盖合法教学班成员。
- **成长/谈话档案**：谈话/观察/家访/家长沟通/奖惩，跟进事项；AI 可读取辅助起草谈话提纲、家长沟通稿。
- **本周关注**：合并连续缺交预警、本周缺交激增、当前学科最近考试临界/薄弱与谈话跟进待办。
- **家长会一页纸**：学生页一键生成打印友好单页。
- **数据备份/恢复**：一键备份、列表、下载、恢复（`~/.exam-tracker-backups`，不被初始化清空）。
- **AI 对话助手**：Anthropic / OpenAI 兼容，只读工具查询本地数据后回答；新增 `list_my_classes` 把「物A1班」解析成 `teaching_class_id`，支持「分析 X 班」类提问。
- **移动端友好 + 本地单机部署 + 跨平台启动器**。

## 技术栈

- **后端**：Python 3.10+ / FastAPI / SQLAlchemy / SQLite / openpyxl
- **前端**：Next.js 14 App Router / TypeScript / Tailwind CSS / Recharts / shadcn/ui
- **AI**：Anthropic SDK / OpenAI SDK / SSE 流式 / tool-use
- **部署**：本地运行（后端 `:8000`、前端 `:3000`），亦可 Docker（群晖 NAS 等）

## 快速开始

### 环境要求
- Python **3.10+**（3.11/3.12 均可）
- Node.js 18+
- macOS / Windows 10/11 / Linux

### 1. 克隆
```bash
git clone https://github.com/wangzuoyuan/Performance-Analysis-Teaching.git
cd Performance-Analysis-Teaching
```

### 2. 配置对话助手（可选）
```bash
cp backend/.env.example backend/.env
```
在 `backend/.env` 填入 API Key（仅用成绩分析页面可先不配；AI 对话需有效 Key）。详见 [对话助手配置](#对话助手配置)。

### 3. 启动
- **macOS**：双击 `启动成绩分析.command`
- **Windows**：双击 `启动成绩分析.bat`
- **任意平台命令行**：
  ```bash
  python run.py start      # 创建环境 + 启动后端 8000 + 前端 3000 + 打开浏览器
  ```

首次启动会自动创建 `backend/.venv`、`npm install`、建库。停止：`python run.py stop`（或双击「停止成绩分析」）。

### 4. 初始化后先配置班级
首次进入后，仪表盘会提示「尚未配置教学班」。到侧栏 **班级配置**（`/settings/classes`）：
1. 选年级 → 系统列出候选（行政班号 + 扫到的教学班标签）→ 建 teaching class。
2. 高一行政班：点「按行政班号同步成员」一键拉人。
3. 走班：粘贴学号 / 姓名 / 花名册导入成员（同名在候选项里消歧）。

之后所有分析页（仪表盘、对比、考试详情、学生检索）都可通过顶栏的**班级范围选择器**在「全部（我教的班）」与某个教学班之间切换。

## 常用命令

```bash
python run.py start                 # 启动后端 + 前端
python run.py stop                  # 停止
python run.py init                  # 完全重置（清空 ~/.exam-tracker/，执行前自动快照）
python run.py backup                # 备份
python run.py restore [备份文件名]   # 恢复（省略则用最新）

# 后端开发
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000
cd backend && source .venv/bin/activate && pytest tests/        # 测试
# 前端开发
cd frontend && npm run dev          # localhost:3000
cd frontend && npx tsc --noEmit     # 类型检查
cd frontend && npm run build        # 生产构建
```

## 数据目录

数据库、上传文件、日志默认在 `~/.exam-tracker/`（Docker 内为 `/data` 挂卷，可用 `EXAM_TRACKER_DIR` 覆盖）。
备份在 `~/.exam-tracker-backups/`（数据目录之外，不被 `init` 清空）。

## 架构与数据模型

**后端**：FastAPI + SQLite（`~/.exam-tracker/db.sqlite`），SQLAlchemy。路由挂 `/api`：`ingest`/`analysis`/`chat`/`homework`/`notes`/`backup`/`teaching`/`auth`。

**成绩表**：`teacher`、`exam`、`upload`、`subject_score`(+`class_label`)、`total_score`、`class_average`(+`class_label`)、`analysis_config`。
**教学班表**（教学版核心）：`teaching_class`（grade+label+subject+kind）、`teaching_class_member`（teaching_class_id ↔ 真实学号，含来源 source）。
**跨学年身份**：`student_identity`（人）、`student_alias`（学号 ↔ 人，分班后学号变更时建链）。
**作业**：`class_roster`(+`class_label`)、`homework_record`、`special_record`、`homework_setting`。`homework_record.subject` 是兼容旧库/旧 API 的字段名，当前业务含义为“作业种类”。**档案**：`student_note`。

**核心口径**：所有按班级的分析从旧的 `WHERE class_num == N` 改为 `resolve_scope(db, teaching_class_id=...)` 解析成成员学号集合（`None`＝全年级）。段位排名仍是**全年级**口径，只是计数落在「我的班成员」子集上。详见 [CLAUDE.md](CLAUDE.md)。

## 对话助手配置（`backend/.env`）

```env
# Anthropic（默认）
CHAT_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-4-6

# 或 OpenAI 兼容
CHAT_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_BASE_URL=             # 留空用官方；填 /v1 结尾可切第三方兼容端点
OPENAI_MODEL=gpt-4o-mini
```

## 部署（Docker / 群晖 NAS）

`docker-compose.yml`（backend + frontend + caddy）+ `Caddyfile`（`:8080` 路径分流）+ `DEPLOY.md`（群晖完整手册）。
登录鉴权仅当设了 `APP_PASSWORD` **且**请求命中 `PUBLIC_HOST`（外网域名）时启用；内网/本地/未设密码一律放行。NAS 上 compose 需带 `-p grade_tracker`。

## 测试

```bash
cd backend && source .venv/bin/activate && pytest tests/
```
覆盖：`api` / `chat_config` / `chat_tools` / `db` / `excel_parser` / `filename_parser` / `homework_parser`（作业种类解析）/ `homework_router` / `notes_router` / `backup_weekly`，教学版新增的 **`test_teaching_router`**（班级 CRUD / 成员 / 四态导入 / 同步 / 当前班）与 **`test_scope`**（范围解析 / 身份链接 / 解除），以及作业看板的 **`test_homework_dashboard`**（范围口径 / 混合智能录入 / 仅姓名成员录缺交 / 占位学号按班隔离迁移 / 同名跨班不串数据）。

**持续集成**：`.github/workflows/ci.yml` 在每次 push 到 `main` 与所有 PR 上跑——后端 `pytest`、前端 `tsc --noEmit` + `next build`。

> 注：`test_homework_router::test_toggle_excluded_roundtrip` 依赖已跑过 `homework/migrate.py`（把旧 `homework.db` 迁入），全新空库下会因花名册为空而跳过失败，属环境依赖，不影响功能。

## 版本

当前版本 **2.0.0**。完整变更见 [CHANGELOG.md](CHANGELOG.md)，历史版本见 [Releases](https://github.com/wangzuoyuan/Performance-Analysis-Teaching/releases)。

## 设计文档

- [CLAUDE.md](CLAUDE.md) —— 架构概览、数据库表、API 端点一览、业务口径（指标选择规则）、数据流关键路径。
- [AGENTS.md](AGENTS.md) —— 面向协作者的工程约定与模块说明。
- [DEPLOY.md](DEPLOY.md) —— 群晖 NAS / Docker 部署手册。

## License

MIT — 见 [LICENSE](LICENSE)。
