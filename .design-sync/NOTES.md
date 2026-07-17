# design-sync 备忘（成绩分析·教学版）

## 仓库形态
- 这是一个 **Next.js 应用**（`frontend/`，包名 `exam-tracker-frontend`），不是可发布的组件库：没有 dist、没有 Storybook。走 **package(synth-entry)** 形态。
- 组件源：15 个 shadcn/ui 原语在 `frontend/src/components/ui/`，其余业务/布局组件在 `frontend/src/components/`(含 `layout/`)。
- PKG_DIR 通过 `--entry ./frontend/.ds-barrel.tsx` 向上走到 `frontend/package.json` 解析得到 = `frontend/`；故 config 内所有相对路径都相对 `frontend/`。

## 构建前置（新克隆必做，产物均 gitignore）
1. `cd frontend && npm ci`（装应用依赖，含 tailwind CLI、react、radix、recharts）
2. `cd .ds-sync`... 见下方「暂存脚本」
3. `node .design-sync/regen-scaffold.mjs` —— 从 `config.json` 重新生成 `frontend/.ds-barrel.tsx`、`.ds-shim.ts`、`.ds-tailwind.config.js` 并编译 `.ds-compiled.css`（cssEntry）。

## 暂存脚本 + 依赖（gitignore 的 `.ds-sync/`）
```
cp -r <skill>/package-build.mjs <skill>/package-validate.mjs <skill>/package-capture.mjs <skill>/resync.mjs <skill>/lib <skill>/storybook .ds-sync/
echo '{"name":"ds-sync-deps","private":true}' > .ds-sync/package.json
(cd .ds-sync && npm i esbuild ts-morph @types/react playwright && npx playwright install chromium)
```

## 构建 / 校验（从 repo 根）
```
node .ds-sync/package-build.mjs --config .design-sync/config.json --node-modules frontend/node_modules --entry ./frontend/.ds-barrel.tsx --out ./ds-bundle
node .ds-sync/package-validate.mjs ./ds-bundle
```

## 关键坑
- **process shim 必需**：Next.js 内部（`next/navigation`、`next/link`）在模块初始化时读 `process.env.__NEXT_*`，浏览器/claude.ai/design 运行时无 `process` → 整个 IIFE 在加载时崩溃、`window.ExamTrackerFrontend` 拿不到任何导出。`frontend/.ds-shim.ts` 作为 barrel **第一条 import**（ESM 按序求值，早于 next 模块）解决。
- **CSS = 编译后的 Tailwind**：`globals.css` 只有 `@tailwind` 指令 + `:root` 变量，没有工具类实体。cssEntry 指向 `.ds-compiled.css`（tailwind CLI 编译，content 含 `src/**` 与 `.design-sync/previews/**`）。**改了 previews 里新用到的工具类，务必先重编 CSS 再 build**（regen-scaffold 会做）。
- **分组**：8 个组（primitives/containers/overlays/layout/app/charts/controls/data-cards）靠 `.design-sync/docs/<Name>.md` 的 `category:` frontmatter stub 设定；`layout/*` 因目录名已落 `layout`。
- **图表宽度**：recharts `ResponsiveContainer` 需要有宽度的父容器，预览里都包了 `width:460`。
- **叠层组件**：Dialog/Sheet 用 `open modal={false}` + 阻止 escape/outside 关闭来静态渲染打开态；overrides 设 `cardMode:single`。Select 预览用关闭态触发器（打开态 popper 定位在无头下不稳）。

## 已知渲染 warn
- 无阻断性 warn。18/6 floor card 属未编写预览，非失败。

## 未编写预览（floor card，可后续增量补）
`ChatDrawer`、`BackupCard`、`HomeworkCard`、`StudentNotes`、`WeeklyFocusCard`、`ClassScopePicker`、`Shell`、`Sidebar`、`Topbar` —— 均依赖运行时数据请求或 next 路由上下文，静态预览需要 mock `fetch`/router 才有意义；目前保留 floor card（组件本身完全可导入）。补法：在 `.design-sync/previews/<Name>.tsx` 里 mock 数据后渲染。

## 评级捕获小改（仅影响截图，不影响交付物）
- `.ds-sync/package-capture.mjs` 的 `settle()` 里加了 `await page.waitForTimeout(1900)`，让 recharts 折线入场动画画完再截图。`.ds-sync/` 是 gitignore、每次 re-sync 从 skill 重新拷贝的——**若 re-sync 后图表评级图只画了一半，重新打这个补丁**。

## Re-sync 风险清单（下次同步要盯的）
- **生成脚手架全部 gitignore**：`frontend/.ds-{barrel.tsx,shim.ts,tailwind.config.js,compiled.css}`。新克隆必须先跑 `regen-scaffold.mjs`，否则 build 找不到入口/CSS。
- **DEFAULT_EXPORTS 列表硬编码在 regen-scaffold.mjs**：若给库新增 default-export 组件并纳入同步，记得往该集合里加名字，否则 barrel 会用 `export *` 漏掉它。
- **HomeworkOverviewCard 被显式排除**（`componentSrcMap` 置 null），与上一版一致；如需纳入自行加回。
- **上一版云端项目结构**（30 组件 / 同样 8 组 / 同名路径）与本次一致，故再采纳覆盖时删除集应为空。
- 预览用的是 mock 数据（写死在 `previews/*.tsx`），与后端真实字段脱耦；组件 props 变更时对照 `<Name>.d.ts` 校准。
