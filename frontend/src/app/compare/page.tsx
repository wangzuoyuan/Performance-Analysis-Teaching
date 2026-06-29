'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip as RTooltip,
  Legend,
  CartesianGrid,
  ResponsiveContainer,
} from 'recharts'
import {
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  ArrowUp,
  ArrowDown,
  Download,
  Printer,
  Info,
  Inbox,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

// ---------- 类型 ----------

/** class_label 已是成品串（高一=「1」/「5」，高二/三=「物A1」/「史B3」）。 */
function displayLabel(label: string | null | undefined): string {
  if (!label) return '—'
  // 纯数字视为行政班号，追加「班」；非数字（走班名）原样
  return /^\d+$/.test(label) ? `${label}班` : label
}

interface ExamMeta {
  id: number
  name: string
  grade?: number | null
  semester?: string | null
  exam_date?: string | null
  exam_type?: string | null
}

interface CompareClass {
  class_label: string
  class_num?: number | null
  class_type?: string | null
  teacher_name?: string | null
  mine: boolean
  /** class_average=官方均分；computed=走班无官方均分，按成员现算。 */
  source: 'class_average' | 'computed'
  main_total_avg: number | null
  five_total_avg?: number | null
  nine_total_avg?: number | null
  plus3_avg: number | null
  total_avg: number | null
}

interface CompareExam {
  exam_id: number
  exam_name: string
  grade?: number | null
  /** 行政班 / 教学班 */
  dimension: '行政班' | '教学班'
  mine_labels: string[]
  classes: CompareClass[]
}

interface ExamDetailClass {
  class_num: number
  class_label?: string | null
  class_type?: string | null
  teacher_name?: string | null
  subject_averages: Record<string, number> | null
  total_averages: Record<string, number> | null
}

interface ExamDetailResp {
  exam: ExamMeta
  class_averages: ExamDetailClass[]
}

type CompareMetric = 'main3' | 'five' | 'plus3' | 'total33'
type MetricSource = 'compare' | 'subject' | 'subject_pair'

interface MetricOption {
  id: string
  label: string
  short: string
  desc: string
  color: string
  source: MetricSource
  field?: keyof CompareClass
  subjectKey?: string
  rawSubjectKey?: string
  gradeSubjectKey?: string
}

const METRIC_DEFS: Record<
  CompareMetric,
  MetricOption & { field: keyof CompareClass }
> = {
  main3: {
    id: 'main3',
    label: '主三门',
    short: '主三门均分',
    source: 'compare',
    field: 'main_total_avg',
    desc: '语数英总分',
    color: '#6366f1',
  },
  five: {
    id: 'five',
    label: '五门',
    short: '五门均分',
    source: 'compare',
    field: 'five_total_avg',
    desc: '语数英物化总分',
    color: '#14b8a6',
  },
  plus3: {
    id: 'plus3',
    label: '+3',
    short: '+3均分',
    source: 'compare',
    field: 'plus3_avg',
    desc: '选科三门总分',
    color: '#55d6c2',
  },
  total33: {
    id: 'total33',
    label: '3+3',
    short: '3+3均分',
    source: 'compare',
    field: 'total_avg',
    desc: '语数英 + 选科总分',
    color: '#ff6b6b',
  },
}

const SUBJECT_COLORS = [
  '#2563eb',
  '#0891b2',
  '#0f766e',
  '#7c3aed',
  '#d97706',
  '#dc2626',
  '#16a34a',
  '#4f46e5',
  '#be123c',
]

const GRADE1_SUBJECT_ORDER = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理']
const GRADE23_BASE_SUBJECT_ORDER = ['语文', '数学', '英语']
const GRADE23_ELECTIVE_SUBJECT_ORDER = ['物理', '化学', '生物', '政治', '历史', '地理']

function subjectMetricLabel(key: string) {
  const [subject, kind] = key.split('_')
  if (kind === '原始') return `${subject}原始均分`
  if (kind === '等级') return `${subject}等级均分`
  return `${key}均分`
}

function subjectMetricShort(key: string) {
  const [subject, kind] = key.split('_')
  if (kind === '原始') return `${subject}原始均分`
  if (kind === '等级') return `${subject}等级均分`
  return `${subject}均分`
}

function subjectPairMetricLabel(subject: string) {
  return `${subject}原始/等级均分`
}

type SortKey = 'class_label' | 'main_total_avg' | 'diff' | 'rank'
type SortDir = 'asc' | 'desc'

export default function ComparePage() {
  const [exams, setExams] = useState<ExamMeta[]>([])
  const [examsLoading, setExamsLoading] = useState(true)

  const [selectedExam, setSelectedExam] = useState<number | null>(null)
  const [compareMetric, setCompareMetric] = useState<string>('main3')

  const [compareData, setCompareData] = useState<CompareExam[]>([])
  const [compareLoading, setCompareLoading] = useState(true)

  const [examDetail, setExamDetail] = useState<ExamDetailResp | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [sortKey, setSortKey] = useState<SortKey>('main_total_avg')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // ---------- fetch: exams ----------
  useEffect(() => {
    setExamsLoading(true)
    fetch('/api/exams')
      .then(r => r.json())
      .then(d => {
        const list: ExamMeta[] = d.exams || []
        setExams(list)
        if (list.length > 0 && selectedExam === null) {
          setSelectedExam(list[0].id)
        }
      })
      .catch(console.error)
      .finally(() => setExamsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ---------- fetch: /api/class/compare (排名表 数据源) ----------
  useEffect(() => {
    setCompareLoading(true)
    const url = selectedExam
      ? `/api/class/compare?exam_id=${selectedExam}`
      : '/api/class/compare'
    fetch(url)
      .then(r => r.json())
      .then(d => setCompareData(d.exams || []))
      .catch(console.error)
      .finally(() => setCompareLoading(false))
  }, [selectedExam])

  // ---------- fetch: /api/exams/{id} (单科均分) ----------
  useEffect(() => {
    if (!selectedExam) {
      setExamDetail(null)
      return
    }
    setDetailLoading(true)
    fetch(`/api/exams/${selectedExam}`)
      .then(r => r.json())
      .then((d: ExamDetailResp) => setExamDetail(d))
      .catch(err => {
        console.error(err)
        setExamDetail(null)
      })
      .finally(() => setDetailLoading(false))
  }, [selectedExam])

  // ---------- 派生：本场对比 ----------
  const currentCompare = useMemo(
    () => compareData.find(e => e.exam_id === selectedExam) || null,
    [compareData, selectedExam],
  )
  const currentExamMeta = useMemo(
    () => exams.find(e => e.id === selectedExam) || null,
    [exams, selectedExam],
  )
  const currentGrade = currentCompare?.grade ?? currentExamMeta?.grade ?? null
  const dimension = currentCompare?.dimension ?? '行政班'

  /** class_label → ExamDetailClass（单科均分表，按 label 索引；缺 label 回落 str(class_num)）。 */
  const detailByLabel = useMemo(() => {
    const m = new Map<string, ExamDetailClass>()
    for (const row of examDetail?.class_averages || []) {
      const label = row.class_label || (row.class_num != null ? String(row.class_num) : null)
      if (label) m.set(label, row)
    }
    return m
  }, [examDetail])

  const subjectMetricOptions = useMemo<MetricOption[]>(() => {
    const rows = examDetail?.class_averages || []
    const availableKeys = new Set<string>()
    rows.forEach(row => {
      Object.entries(row.subject_averages || {}).forEach(([key, value]) => {
        if (typeof value === 'number') availableKeys.add(key)
      })
    })

    if (currentGrade === 1) {
      return GRADE1_SUBJECT_ORDER
        .filter(key => availableKeys.has(key))
        .map((key, index) => ({
          id: `subject:${key}`,
          label: subjectMetricLabel(key),
          short: subjectMetricShort(key),
          desc: subjectMetricLabel(key),
          color: SUBJECT_COLORS[index % SUBJECT_COLORS.length],
          source: 'subject' as const,
          subjectKey: key,
        }))
    }

    const baseOptions = GRADE23_BASE_SUBJECT_ORDER
      .filter(key => availableKeys.has(key))
      .map((key, index) => ({
        id: `subject:${key}`,
        label: subjectMetricLabel(key),
        short: subjectMetricShort(key),
        desc: subjectMetricLabel(key),
        color: SUBJECT_COLORS[index % SUBJECT_COLORS.length],
        source: 'subject' as const,
        subjectKey: key,
      }))

    const pairOptions = GRADE23_ELECTIVE_SUBJECT_ORDER
      .filter(subject => availableKeys.has(`${subject}_原始`) && availableKeys.has(`${subject}_等级`))
      .map((subject, index) => ({
        id: `subject-pair:${subject}`,
        label: subjectPairMetricLabel(subject),
        short: subjectPairMetricLabel(subject),
        desc: `${subject}原始分均分与等级分均分`,
        color: SUBJECT_COLORS[(index + baseOptions.length) % SUBJECT_COLORS.length],
        source: 'subject_pair' as const,
        rawSubjectKey: `${subject}_原始`,
        gradeSubjectKey: `${subject}_等级`,
      }))

    return [...baseOptions, ...pairOptions]
  }, [currentGrade, examDetail])

  const metricOptions = useMemo<MetricOption[]>(() => {
    const totalOptions =
      currentGrade === 1
        ? [METRIC_DEFS.main3, METRIC_DEFS.five]
        : [METRIC_DEFS.main3, METRIC_DEFS.plus3, METRIC_DEFS.total33]
    return [...totalOptions, ...subjectMetricOptions]
  }, [currentGrade, subjectMetricOptions])

  const activeMetric = metricOptions.some(option => option.id === compareMetric)
    ? compareMetric
    : 'main3'
  const metricDef = metricOptions.find(option => option.id === activeMetric) || METRIC_DEFS.main3

  useEffect(() => {
    if (metricOptions.length > 0 && !metricOptions.some(option => option.id === compareMetric)) {
      setCompareMetric(metricOptions[0].id)
    }
  }, [compareMetric, metricOptions])

  /** class_label → 当前口径数值。 */
  const metricValueByLabel = useMemo(() => {
    const values = new Map<string, { value: number; mine: boolean; source: CompareClass['source'] }>()

    if (metricDef.source === 'subject_pair') {
      const key = metricDef.gradeSubjectKey
      if (!key) return values
      for (const [label, row] of detailByLabel) {
        const value = row.subject_averages?.[key]
        if (typeof value === 'number') {
          values.set(label, {
            value,
            mine: currentCompare?.classes.find(c => c.class_label === label)?.mine ?? false,
            source: 'class_average',
          })
        }
      }
      return values
    }

    if (metricDef.source === 'subject') {
      const key = metricDef.subjectKey
      if (!key) return values
      for (const [label, row] of detailByLabel) {
        const value = row.subject_averages?.[key]
        if (typeof value === 'number') {
          values.set(label, {
            value,
            mine: currentCompare?.classes.find(c => c.class_label === label)?.mine ?? false,
            source: 'class_average',
          })
        }
      }
      return values
    }

    // compare 口径：直接取 compare.classes
    if (!currentCompare || !metricDef.field) return values
    for (const row of currentCompare.classes) {
      const value = row[metricDef.field]
      if (typeof value === 'number') {
        values.set(row.class_label, {
          value,
          mine: row.mine,
          source: row.source,
        })
      }
    }
    return values
  }, [currentCompare, detailByLabel, metricDef])

  const chartBars = useMemo(() => {
    if (metricDef.source !== 'subject_pair') {
      return [{ key: metricDef.short, name: metricDef.short, color: metricDef.color }]
    }
    const subject = metricDef.id.replace('subject-pair:', '')
    return [
      { key: `${subject}原始均分`, name: `${subject}原始均分`, color: '#2563eb' },
      { key: `${subject}等级均分`, name: `${subject}等级均分`, color: '#0f766e' },
    ]
  }, [metricDef])

  // 图表数据：班级 x 当前口径均分（按 label 组织）
  const chartData = useMemo(() => {
    const labels =
      currentCompare?.classes.map(c => c.class_label) ||
      Array.from(detailByLabel.keys())
    if (labels.length === 0) return []
    return labels.map(label => {
      const row: Record<string, number | string | boolean> = {
        classLabel: displayLabel(label),
        class_label: label,
        mine: currentCompare?.classes.find(c => c.class_label === label)?.mine ?? false,
      }
      if (metricDef.source === 'subject_pair') {
        const avgRow = detailByLabel.get(label)
        const rawValue = metricDef.rawSubjectKey ? avgRow?.subject_averages?.[metricDef.rawSubjectKey] : undefined
        const gradeValue = metricDef.gradeSubjectKey ? avgRow?.subject_averages?.[metricDef.gradeSubjectKey] : undefined
        if (typeof rawValue === 'number') row[chartBars[0].key] = Number(rawValue.toFixed(1))
        if (typeof gradeValue === 'number') row[chartBars[1].key] = Number(gradeValue.toFixed(1))
        return row
      }

      const entry = metricValueByLabel.get(label)
      if (entry && typeof entry.value === 'number') row[chartBars[0].key] = Number(entry.value.toFixed(1))
      return row
    })
  }, [chartBars, currentCompare, detailByLabel, metricDef, metricValueByLabel])

  // 排名表数据
  const rankRows = useMemo(() => {
    const rows = Array.from(metricValueByLabel.entries()).map(([class_label, meta]) => ({
      class_label,
      mine: meta.mine,
      source: meta.source,
      main_total_avg: meta.value,
      diff: 0,
      rank: 0,
    }))
    if (rows.length === 0) return [] as (typeof rows)[number][]

    const total = rows.reduce((s, r) => s + r.main_total_avg, 0)
    const gradeAvg = total / rows.length

    const withMeta = rows.map(r => ({
      ...r,
      diff: r.main_total_avg - gradeAvg,
    }))

    // 名次：按当前口径均分降序
    const ranked = [...withMeta]
      .sort((a, b) => b.main_total_avg - a.main_total_avg)
      .map((r, idx) => ({ ...r, rank: idx + 1 }))

    // 应用用户排序
    const sorted = [...ranked].sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1
      const va = a[sortKey]
      const vb = b[sortKey]
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
      return String(va).localeCompare(String(vb), 'zh-Hans-CN') * dir
    })
    return sorted
  }, [metricValueByLabel, sortKey, sortDir])

  const onSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'class_label' ? 'asc' : 'desc')
    }
  }

  const sortIcon = (key: SortKey) => {
    if (sortKey !== key) return <ChevronsUpDown className="ml-1 h-3.5 w-3.5 opacity-50" />
    return sortDir === 'asc' ? (
      <ChevronUp className="ml-1 h-3.5 w-3.5" />
    ) : (
      <ChevronDown className="ml-1 h-3.5 w-3.5" />
    )
  }

  const formatExamLabel = (e: ExamMeta) => {
    const date = e.exam_date ? ` · ${e.exam_date}` : ''
    return `${e.name}${date}`
  }

  const isLoadingChart = detailLoading || examsLoading
  const isLoadingTable = compareLoading || examsLoading

  const myLabels = currentCompare?.mine_labels ?? []

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-6">
        {/* ---------- 顶部标题 ---------- */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              班级对比
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              跨{dimension}各科均分横向对比，我教的班高亮
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* TODO: 导出 CSV / 打印 暂未实现 */}
            <Button variant="outline" size="sm" disabled>
              <Download className="mr-1.5 h-4 w-4" />
              导出 CSV
            </Button>
            <Button variant="outline" size="sm" disabled>
              <Printer className="mr-1.5 h-4 w-4" />
              打印
            </Button>
          </div>
        </div>

        {/* ---------- Filter 行（sticky） ---------- */}
        <div
          className={cn(
            'sticky top-14 z-20 -mx-1 rounded-xl border border-slate-200',
            'bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/70',
          )}
        >
          <div className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <span className="shrink-0 text-sm font-medium text-slate-700">选择考试</span>
              <Select
                value={selectedExam ? String(selectedExam) : undefined}
                onValueChange={v => setSelectedExam(Number(v))}
                disabled={examsLoading || exams.length === 0}
              >
                <SelectTrigger className="h-9 w-full sm:w-[260px]">
                  <SelectValue placeholder={examsLoading ? '加载中…' : '请选择考试'} />
                </SelectTrigger>
                <SelectContent>
                  {exams.map(e => (
                    <SelectItem key={e.id} value={String(e.id)}>
                      {formatExamLabel(e)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex w-full items-center gap-2 sm:w-auto">
              <span className="shrink-0 text-sm font-medium text-slate-700">统计口径</span>
              <Select
                value={activeMetric}
                onValueChange={setCompareMetric}
                disabled={metricOptions.length === 0}
              >
                <SelectTrigger className="h-9 w-full sm:w-[220px]">
                  <SelectValue placeholder="请选择统计口径" />
                </SelectTrigger>
                <SelectContent>
                  {metricOptions.map(option => (
                    <SelectItem key={option.id} value={option.id}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              <span className="text-sm text-slate-500">我教的班</span>
              {myLabels.length > 0 ? (
                myLabels.map(label => (
                  <Badge
                    key={label}
                    variant="secondary"
                    className="bg-brand-50 text-brand-700 hover:bg-brand-50"
                  >
                    {displayLabel(label)}
                  </Badge>
                ))
              ) : (
                <Badge variant="outline" className="text-slate-400">
                  未设置
                </Badge>
              )}
            </div>
          </div>
        </div>

        {/* ---------- 主体 ---------- */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          {/* 左：柱状图 */}
          <Card className="lg:col-span-3">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-base font-semibold text-slate-800">
                各{dimension}{metricDef.short}
              </CardTitle>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:bg-slate-50 hover:text-slate-600"
                  >
                    <Info className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="left" className="max-w-[260px]">
                  当前按{metricDef.desc}对比；我教的班柱子高亮，其它班柱子半透明。带「估算」标签的为走班无官方均分、按成员现算。
                </TooltipContent>
              </Tooltip>
            </CardHeader>
            <CardContent>
              {isLoadingChart ? (
                <Skeleton className="h-[380px] w-full" />
              ) : chartData.length === 0 ? (
                <EmptyState
                  title={selectedExam ? '该考试无对比数据' : '请先选择考试'}
                  desc="班级均分表（ClassAverage）暂未导入，无法渲染图表。"
                  height={380}
                />
              ) : (
                <ResponsiveContainer width="100%" height={380}>
                  <BarChart
                    data={chartData}
                    margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="#e2e8f0"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="classLabel"
                      tick={{ fill: '#475569', fontSize: 12 }}
                      tickLine={false}
                      axisLine={{ stroke: '#cbd5e1' }}
                    />
                    <YAxis
                      domain={[0, 'dataMax + 20']}
                      tick={{ fill: '#475569', fontSize: 12 }}
                      tickLine={false}
                      axisLine={{ stroke: '#cbd5e1' }}
                    />
                    <RTooltip
                      cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                      contentStyle={{
                        borderRadius: 8,
                        border: '1px solid #e2e8f0',
                        fontSize: 12,
                        boxShadow: '0 4px 12px rgba(15, 23, 42, 0.08)',
                      }}
                      formatter={(v: number | string) =>
                        typeof v === 'number' ? v.toFixed(1) : v
                      }
                    />
                    <Legend
                      wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                      iconType="circle"
                    />
                    {chartBars.map((bar, barIndex) => (
                      <Bar
                        key={bar.key}
                        dataKey={bar.key}
                        name={bar.name}
                        radius={[4, 4, 0, 0]}
                        maxBarSize={metricDef.source === 'subject_pair' ? 16 : 28}
                      >
                        {chartData.map((row, idx) => {
                          const isMine = row.mine === true
                          return (
                            <Cell
                              key={`${bar.key}-${idx}`}
                              fill={
                                isMine
                                  ? bar.color
                                  : barIndex === 0
                                    ? '#cbd5e1'
                                    : '#94a3b8'
                              }
                              fillOpacity={isMine ? 1 : 0.45}
                            />
                          )
                        })}
                      </Bar>
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* 右：排名表 */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-slate-800">
                {dimension}排名表
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoadingTable ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : rankRows.length === 0 ? (
                <EmptyState
                  title={selectedExam ? '该考试无对比数据' : '请先选择考试'}
                  desc={`未找到该场考试的${metricDef.short}数据。`}
                  height={320}
                />
              ) : (
                <div className="overflow-hidden rounded-lg border border-slate-200">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50 hover:bg-slate-50">
                        <SortableHead
                          label={dimension}
                          active={sortKey === 'class_label'}
                          dir={sortDir}
                          onClick={() => onSort('class_label')}
                          icon={sortIcon('class_label')}
                        />
                        <SortableHead
                          label={metricDef.short}
                          active={sortKey === 'main_total_avg'}
                          dir={sortDir}
                          onClick={() => onSort('main_total_avg')}
                          icon={sortIcon('main_total_avg')}
                          align="right"
                        />
                        <SortableHead
                          label="较年级均差"
                          active={sortKey === 'diff'}
                          dir={sortDir}
                          onClick={() => onSort('diff')}
                          icon={sortIcon('diff')}
                          align="right"
                        />
                        <SortableHead
                          label="名次"
                          active={sortKey === 'rank'}
                          dir={sortDir}
                          onClick={() => onSort('rank')}
                          icon={sortIcon('rank')}
                          align="right"
                        />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rankRows.map(row => {
                        const positive = row.diff >= 0
                        return (
                          <TableRow
                            key={row.class_label}
                            className={cn(
                              'transition-colors',
                              row.mine &&
                                'border-l-2 border-brand-500 bg-brand-50 hover:bg-brand-50',
                            )}
                          >
                            <TableCell className="font-medium text-slate-800">
                              <div className="flex flex-col gap-0.5">
                                <div className="flex items-center gap-2">
                                  <span>{displayLabel(row.class_label)}</span>
                                  {row.mine && (
                                    <Badge
                                      variant="secondary"
                                      className="h-5 bg-brand-100 px-1.5 text-[10px] text-brand-700"
                                    >
                                      我的班
                                    </Badge>
                                  )}
                                  {row.source === 'computed' && (
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <span className="inline-flex items-center rounded bg-amber-100 px-1 text-[10px] font-medium text-amber-700">
                                          估算
                                        </span>
                                      </TooltipTrigger>
                                      <TooltipContent side="top" className="max-w-[200px]">
                                        走班无官方均分，按该教学班成员成绩现算。
                                      </TooltipContent>
                                    </Tooltip>
                                  )}
                                </div>
                                {row.source === 'computed' && (
                                  <span className="text-[10px] text-slate-400">
                                    {displayLabel(row.class_label)}（现算）
                                  </span>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-slate-800">
                              {row.main_total_avg.toFixed(1)}
                            </TableCell>
                            <TableCell
                              className={cn(
                                'text-right tabular-nums font-medium',
                                positive ? 'text-success-500' : 'text-danger-500',
                              )}
                            >
                              <span className="inline-flex items-center justify-end">
                                {positive ? (
                                  <ArrowUp className="mr-0.5 h-3.5 w-3.5" />
                                ) : (
                                  <ArrowDown className="mr-0.5 h-3.5 w-3.5" />
                                )}
                                {Math.abs(row.diff).toFixed(1)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-slate-600">
                              #{row.rank}
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </TooltipProvider>
  )
}

// ---------- 子组件 ----------

interface SortableHeadProps {
  label: string
  active: boolean
  dir: SortDir
  onClick: () => void
  icon: React.ReactNode
  align?: 'left' | 'right'
}

function SortableHead({ label, onClick, icon, align = 'left' }: SortableHeadProps) {
  return (
    <TableHead
      className={cn(
        'cursor-pointer select-none text-slate-600 hover:text-slate-900',
        align === 'right' && 'text-right',
      )}
      onClick={onClick}
    >
      <span
        className={cn(
          'inline-flex items-center',
          align === 'right' && 'justify-end',
        )}
      >
        {label}
        {icon}
      </span>
    </TableHead>
  )
}

function EmptyState({
  title,
  desc,
  height = 320,
}: {
  title: string
  desc?: string
  height?: number
}) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center"
      style={{ height }}
    >
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        <Inbox className="h-6 w-6" />
      </div>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {desc && <p className="mt-1 max-w-[260px] text-xs text-slate-500">{desc}</p>}
    </div>
  )
}
