# 成绩分析（教学版）

> 任课老师的多教学班成绩与教学质量分析 Web 应用。
> 一位老师同时任教**多个教学班**（高一＝行政班数字，高二/三可为走班班名如「物A1」「史B3」），
> 所有质量分析按「我教的教学班成员集合」进行，并支持跨学年学情继承。

由「成绩分析（班主任版）」移植而来：把全系统「按班级」的口径从**单一数字行政班号**
升级为**老师可配置的多个教学班**（字符串标签 `class_label`）。移植设计与执行蓝图见根目录
`01–06` 文档。

本项目按 MIT License 开源，可自由使用、修改和二次分发。

---

## 功能特性

### 教学班（核心）
- **多教学班模型**：老师配置任意多个教学班；高一教学班即行政班（数字），高二/三支持走班名（`物A1`/`史B3`）。
- **班级配置向导**（`/settings/classes`）：按年级建班、维护成员、批量导入（学号/姓名/花名册）、按行政班号一键同步、排序删班、设当前班。
- **成员四态导入**：粘贴学号或姓名清单，返回「已匹配 / 同名待消歧 / 未匹配」三态；同名候选项附行政班与最近名次辅助辨认。
- **两种仪表盘**：总览（跨我所有班聚合，学生旁标教学班）+ 分班（选定单班后的专属视图），顶栏一键切换。
- **跨学年学情继承**：分班导致学号变更时，以「姓名确认 + 学号对照表」人工建链，让跨学年画像/趋势/档案接续（详见 `06-学号变更与学情继承.md`）。

### 成绩分析
- **Excel 批量导入**：学生成绩明细表 + 班级均分表；自动识别教学班/走班列（`教学班`/`走班`/`选科班` 等表头关键字），写入 `class_label`；无该列时行为不变。
- **高一 / 高二高三双口径**：高一主三门/五门/九门；高二/三主三门/+3/3+3 与选考等级分。
- **考试详情页**：班级均分、学生成绩明细（带教学班徽章）、名次段分布（按教学班分组并高亮我的班）、排名频次、排名区间筛选、重点关注名单。
- **可自定义关注段位**：高分段/临界段/薄弱段区间可调，页面与 AI 口径同步。
- **历次段位趋势**、**排名筛选与频次统计**、**多场进退步趋势排行**。
- **班级对比页（D2）**：展示全年级所有班，高亮我教的多个班；走班无官方均分时按成员现算并标「估算」。
- **学生画像页**：跨学年主三门/五门/+3/3+3 趋势、单科历史、历次明细、教学班内排名（标注口径）、学段履历。

### 作业 / 档案 / AI / 备份
- **作业跟踪**：智能文本录入缺交/请假/迟到，看板（每日趋势/各科占比/排行/连续缺交预警）、自动导出 Excel、花名册排除开关、学期配置。
- **缺交 × 成绩相关性**：缺交次数与排名散点 + 各科皮尔逊系数排序。
- **成长/谈话档案**：谈话/观察/家访/家长沟通/奖惩，跟进事项；AI 可读取辅助起草谈话提纲、家长沟通稿。
- **本周关注**：合并连续缺交预警、本周缺交激增、最近考试临界/薄弱/偏科、谈话跟进待办。
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
**作业**：`class_roster`(+`class_label`)、`homework_record`、`special_record`、`homework_setting`。**档案**：`student_note`。

**核心口径**：所有按班级的分析从旧的 `WHERE class_num == N` 改为 `resolve_scope(db, teaching_class_id=...)` 解析成成员学号集合（`None`＝全年级）。段位排名仍是**全年级**口径，只是计数落在「我的班成员」子集上。详见 [CLAUDE.md](CLAUDE.md) 与 `01–06` 蓝图。

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
覆盖：`api` / `chat_config` / `chat_tools` / `db` / `excel_parser` / `filename_parser` / `homework_parser` / `homework_router` / `notes_router` / `backup_weekly`，以及教学版新增的 **`test_teaching_router`**（班级 CRUD / 成员 / 四态导入 / 同步 / 当前班）与 **`test_scope`**（范围解析 / 身份链接 / 解除）。

> 注：`test_homework_router::test_toggle_excluded_roundtrip` 依赖已跑过 `homework/migrate.py`（把旧 `homework.db` 迁入），全新空库下会因花名册为空而跳过失败，属环境依赖，不影响功能。

## 设计文档

| 文件 | 内容 |
|------|------|
| [01-需求与设计决策.md](01-需求与设计决策.md) | 需求拆解、已确认决策、核心概念、口径 |
| [02-数据模型蓝图.md](02-数据模型蓝图.md) | 新表/改表、迁移策略、成员来源 |
| [03-后端改造蓝图.md](03-后端改造蓝图.md) | scope 解析器、端点改造、解析器扩展、对话工具 |
| [04-前端改造蓝图.md](04-前端改造蓝图.md) | 范围选择器、双仪表盘、对比/学生/考试页改造 |
| [05-执行步骤清单.md](05-执行步骤清单.md) | 分阶段执行顺序与里程碑 |
| [06-学号变更与学情继承.md](06-学号变更与学情继承.md) | 跨学年身份层（姓名确认 + 对照表） |

## License

MIT — 见 [LICENSE](LICENSE)。
