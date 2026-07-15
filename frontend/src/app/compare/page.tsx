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
  Info,
  Inbox,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
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

function displayLabel(label: string | null | undefined): string {
  if (!label) return '—'
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
  teaching_class_id: number
  class_label: string
  member_count: number
  subject_avg: number | null
  score_basis: string
  source: string
  rank: number | null
}

interface CompareExam {
  exam_id: number
  exam_name: string
  grade?: number | null
  teaching_subject?: string | null
  score_basis?: string | null
  overall_subject_avg: number | null
  classes: CompareClass[]
}

type SortKey = 'class_label' | 'subject_avg' | 'diff' | 'rank'
type SortDir = 'asc' | 'desc'

export default function ComparePage() {
  const [exams, setExams] = useState<ExamMeta[]>([])
  const [examsLoading, setExamsLoading] = useState(true)

  const [selectedExam, setSelectedExam] = useState<number | null>(null)

  const [compareData, setCompareData] = useState<CompareExam[]>([])
  const [compareLoading, setCompareLoading] = useState(true)

  const [sortKey, setSortKey] = useState<SortKey>('subject_avg')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // ---------- fetch: exams ----------
  useEffect(() => {
    setExamsLoading(true)
    fetch('/api/exams')
      .then((r) => r.json())
      .then((d) => {
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

  // ---------- fetch: /api/class/compare（当前学科契约） ----------
  useEffect(() => {
    setCompareLoading(true)
    const url = selectedExam
      ? `/api/class/compare?exam_id=${selectedExam}`
      : '/api/class/compare'
    fetch(url)
      .then((r) => r.json())
      .then((d) => setCompareData(d.exams || []))
      .catch(console.error)
      .finally(() => setCompareLoading(false))
  }, [selectedExam])

  // ---------- 派生：本场对比 ----------
  const currentCompare = useMemo(
    () => compareData.find((e) => e.exam_id === selectedExam) || null,
    [compareData, selectedExam],
  )
  const currentExamMeta = useMemo(
    () => exams.find((e) => e.id === selectedExam) || null,
    [exams, selectedExam],
  )
  const teachingSubject = currentCompare?.teaching_subject ?? null
  const scoreBasis = currentCompare?.score_basis ?? 'raw_score'
  const basisLabel = scoreBasis === 'grade_score' ? '等级分' : '原始分'
  const overallAvg = currentCompare?.overall_subject_avg ?? null

  const metricShort = `${teachingSubject ?? '当前学科'}${basisLabel}均分`

  // 图表数据
  const chartData = useMemo(() => {
    if (!currentCompare) return []
    return currentCompare.classes.map((c) => ({
      classLabel: displayLabel(c.class_label),
      class_label: c.class_label,
      subject_avg: c.subject_avg,
      member_count: c.member_count,
    }))
  }, [currentCompare])

  // 排名表数据
  const rankRows = useMemo(() => {
    if (!currentCompare) return []
    const overall = currentCompare.overall_subject_avg ?? null
    const rows = currentCompare.classes.map((c) => ({
      class_label: c.class_label,
      teaching_class_id: c.teaching_class_id,
      member_count: c.member_count,
      subject_avg: c.subject_avg,
      diff: overall != null && c.subject_avg != null ? c.subject_avg - overall : null,
      rank: c.rank,
    }))
    // 应用用户排序
    return [...rows].sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1
      const va = a[sortKey]
      const vb = b[sortKey]
      if (typeof va === 'number' && typeof vb === 'number') {
        if (va === null && vb === null) return 0
        if (va === null) return 1
        if (vb === null) return -1
        return (va - vb) * dir
      }
      return String(va).localeCompare(String(vb), 'zh-Hans-CN') * dir
    })
  }, [currentCompare, sortKey, sortDir])

  const onSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
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

  const isLoading = compareLoading || examsLoading

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
              {teachingSubject
                ? `${teachingSubject}（${basisLabel}）· 我教的教学班横向对比`
                : '当前任教学科教学班横向对比'}
            </p>
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
                onValueChange={(v) => setSelectedExam(Number(v))}
                disabled={examsLoading || exams.length === 0}
              >
                <SelectTrigger className="h-9 w-full sm:w-[260px]">
                  <SelectValue placeholder={examsLoading ? '加载中…' : '请选择考试'} />
                </SelectTrigger>
                <SelectContent>
                  {exams.map((e) => (
                    <SelectItem key={e.id} value={String(e.id)}>
                      {formatExamLabel(e)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {overallAvg != null && (
              <div className="ml-auto flex items-center gap-1.5">
                <span className="text-sm text-slate-500">总体均分</span>
                <Badge variant="secondary" className="bg-brand-50 text-brand-700 hover:bg-brand-50">
                  {overallAvg.toFixed(1)}
                </Badge>
              </div>
            )}
          </div>
        </div>

        {/* ---------- 主体 ---------- */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          {/* 左：柱状图 */}
          <Card className="lg:col-span-3">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-base font-semibold text-slate-800">
                各教学班{metricShort}
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
                  当前按{teachingSubject ?? '当前学科'}的{basisLabel}均分对比，仅含我教的教学班。
                </TooltipContent>
              </Tooltip>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <Skeleton className="h-[380px] w-full" />
              ) : chartData.length === 0 ? (
                <EmptyState
                  title={selectedExam ? '该考试无对比数据' : '请先选择考试'}
                  desc="当前学科在合法教学班范围内暂无真实分数。"
                  height={380}
                />
              ) : (
                <ResponsiveContainer width="100%" height={380}>
                  <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
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
                    <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} iconType="circle" />
                    <Bar
                      dataKey="subject_avg"
                      name={metricShort}
                      fill="#6366f1"
                      radius={[4, 4, 0, 0]}
                      maxBarSize={28}
                    >
                      {chartData.map((_row, idx) => (
                        <Cell key={idx} fill="#6366f1" fillOpacity={0.9} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* 右：排名表 */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-slate-800">
                教学班排名表
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : rankRows.length === 0 ? (
                <EmptyState
                  title={selectedExam ? '该考试无对比数据' : '请先选择考试'}
                  desc={`未找到该场考试的${metricShort}数据。`}
                  height={320}
                />
              ) : (
                <div className="overflow-hidden rounded-lg border border-slate-200">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50 hover:bg-slate-50">
                        <SortableHead
                          label="教学班"
                          active={sortKey === 'class_label'}
                          dir={sortDir}
                          onClick={() => onSort('class_label')}
                          icon={sortIcon('class_label')}
                        />
                        <SortableHead
                          label={metricShort}
                          active={sortKey === 'subject_avg'}
                          dir={sortDir}
                          onClick={() => onSort('subject_avg')}
                          icon={sortIcon('subject_avg')}
                          align="right"
                        />
                        <SortableHead
                          label="较总体均差"
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
                      {rankRows.map((row) => {
                        const positive = (row.diff ?? 0) >= 0
                        return (
                          <TableRow key={row.class_label} className="transition-colors">
                            <TableCell className="font-medium text-slate-800">
                              <div className="flex items-center gap-2">
                                <span>{displayLabel(row.class_label)}</span>
                                <span className="text-[10px] text-slate-400">
                                  {row.member_count}人
                                </span>
                              </div>
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-slate-800">
                              {row.subject_avg != null ? row.subject_avg.toFixed(1) : '—'}
                            </TableCell>
                            <TableCell
                              className={cn(
                                'text-right tabular-nums font-medium',
                                row.diff == null
                                  ? 'text-slate-400'
                                  : positive
                                  ? 'text-success-500'
                                  : 'text-danger-500',
                              )}
                            >
                              {row.diff == null ? (
                                '—'
                              ) : (
                                <span className="inline-flex items-center justify-end">
                                  {positive ? (
                                    <ArrowUp className="mr-0.5 h-3.5 w-3.5" />
                                  ) : (
                                    <ArrowDown className="mr-0.5 h-3.5 w-3.5" />
                                  )}
                                  {Math.abs(row.diff).toFixed(1)}
                                </span>
                              )}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-slate-600">
                              {row.rank != null ? `#${row.rank}` : '—'}
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
      <span className={cn('inline-flex items-center', align === 'right' && 'justify-end')}>
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
