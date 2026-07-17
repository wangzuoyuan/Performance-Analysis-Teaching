## 成绩分析·教学版 设计系统 — 使用约定

这是一套基于 **shadcn/ui + Radix + Tailwind CSS** 的 React 组件库，服务于一款「高中成绩 / 作业分析」教务应用。所有组件从 `window.ExamTrackerFrontend` 暴露；样式为 **Tailwind 工具类**，配合 `styles.css` 中的品牌 token。

### 上手与包裹

- **无需全局 Provider**。绝大多数组件（Button、Card、Table、Badge、Input、Tabs、Dialog、Sheet、Select、Progress…）直接使用即可，样式来自 `styles.css`（务必引入）。
- **例外：Tooltip 必须包在 `TooltipProvider` 内**——`<TooltipProvider><Tooltip>…</Tooltip></TooltipProvider>`，否则 `TooltipContent` 不渲染。
- **Dialog / Sheet / Select** 是 Radix 叠层组件：用 `Dialog` + `DialogContent`、`Sheet` + `SheetContent`（`side="right|left|top|bottom"`）、`Select` + `SelectTrigger`/`SelectContent`/`SelectItem` 组合；受控用 `open` / `defaultOpen`。
- 图表（TrendLineChart / SubjectScatter / RankBandStackedBar / BandTrendChart）基于 recharts，内部用 `ResponsiveContainer`，**必须放在有明确宽度的父容器里**（如 `<div style={{width:460}}>`），否则测不到尺寸、渲染为空。

### 样式惯用法：Tailwind 工具类 + 品牌 token

用 Tailwind 工具类做布局与排版；配色优先使用下列**品牌色阶**（定义于 `tailwind.config.js` / `styles.css`）：

| 语义 | 类名族（示例） |
|---|---|
| 主色 / 强调 | `bg-brand-600` `hover:bg-brand-700` `text-brand-600` `border-brand-500`（`brand` 有 50/100/200/300/500/600/700/900） |
| 成功 / 进步 | `bg-success-50` `text-success-500` `text-success-600` |
| 警示 / 临界 | `bg-warning-50` `text-warning-500`（另有 600/700） |
| 危险 / 薄弱 / 删除 | `bg-danger-500` `text-danger-500`（另有 50/400/600） |
| 中性 | Tailwind 原生 `slate-*`（`text-slate-900` `bg-slate-100` `border-slate-200`） |

语义化 CSS 变量（HSL）也可用于 `bg-background` / `text-foreground` / `border` / `bg-muted` / `text-muted-foreground` 等——它们由 `styles.css` 的 `:root` 定义，`--radius` 控制圆角。

- **Badge** 的品牌状态用 `variant`：`default`(主色) / `secondary` / `success` / `warning` / `destructive` / `outline`——教务语义（已提交=success、临界=warning、连续缺交=destructive）直接映射到这些 variant，不要自己写颜色类。
- **Button** 的 `variant`：`default`(主色) / `secondary` / `outline` / `destructive` / `ghost` / `link`；`size`：`default` / `sm` / `lg` / `icon`。
- 内容用真实教务语料（班级如「高二(3)班」、学科「物理」、指标「平均分 / 及格率 / 段位 / 缺交」），不要 `foo` / `test`。

### 真相来源

- 全部样式与 token 定义在 **`styles.css`**（及其 `@import` 的 `_ds_bundle.css`）——改配色前先读它。
- 每个组件的 API 见其目录下的 `<Name>.d.ts`，用法见 `<Name>.prompt.md`。
- 复合组件的子件命名遵循 shadcn 约定：`Card`→`CardHeader`/`CardTitle`/`CardDescription`/`CardContent`/`CardFooter`；`Table`→`TableHeader`/`TableBody`/`TableRow`/`TableHead`/`TableCell`/`TableCaption`；`Tabs`→`TabsList`/`TabsTrigger`/`TabsContent`。

### 一个惯用示例

```tsx
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter, Badge, Button } from 'exam-tracker-frontend';

function ClassStatCard() {
  return (
    <Card className="max-w-sm">
      <CardHeader>
        <CardTitle>班级平均分</CardTitle>
        <CardDescription>高二(3)班 · 物理 · 期中考试</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold text-brand-600">78.4</div>
        <div className="mt-1 text-sm text-success-600">较上次 +3.2 分</div>
      </CardContent>
      <CardFooter>
        <Badge variant="success">年级第 2</Badge>
      </CardFooter>
    </Card>
  );
}
```
