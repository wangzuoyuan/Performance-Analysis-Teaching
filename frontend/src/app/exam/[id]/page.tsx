'use client'

import { Fragment, useEffect, useMemo, useState } from 'react'
import type { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  BookOpen,
  ChevronLeft,
  Download,
  Hash,
  Search,
  TrendingUp,
  Users,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { BandTrendChart } from '@/components'
import { ClassScopePicker } from '@/components/ClassScopePicker'
import { useClassScope, formatClassChip } from '@/lib/class-scope'
import { formatGradeLabel } from '@/lib/labels'

interface ExamDetail {
  id: number
  name: string
  grade: number
  semester?: string | null
  exam_date: string
  exam_type?: string | null
}

interface ClassAverage {
  class_num: number
  class_label?: string | null
  class_type?: string | null
  teacher_name?: string | null
  subject_averages?: Record<string, number | null> | null
  total_averages?: Record<string, number | null> | null
}

interface ExamStats {
  total_students?: number | null
  avg_main_total?: number | null
  max_total?: number | null
  min_total?: number | null
  rank_min?: number | null
  rank_max?: number | null
  by_total_type?: Record<string, TotalTypeStats | undefined> | null
}

interface TotalTypeStats {
  count?: number | null
  avg?: number | null
  max?: number | null
  min?: number | null
  rank_min?: number | null
  rank_max?: number | null
}

interface ExamApiResponse {
  exam: ExamDetail
  class_averages?: ClassAverage[]
  stats?: ExamStats
  // 下面这些后端目前不返回，预留兼容
  focus_list?: FocusStudent[]
  students?: StudentRow[]
  rank_bands?: RankBandEntry[]
  band_config?: BandConfig
  rank_distribution?: RankDistributionEntry[]
}

interface FocusStudent {
  student_id: string
  name: string
  class_num?: number | null
  class_label?: string | null
  xueji_rank?: number | null
  total_score?: number | null
  issues?: string[]
  issue?: string
}

interface StudentRow {
  student_id: string
  name: string
  class_num?: number | null
  xueji?: number | null
  subject_scores?: Record<string, number | null> | null
  subject_grade_scores?: Record<string, number | null> | null
  subject_percentiles?: Record<string, number | null> | null
  total_scores?: Record<
    string,
    {
      score?: number | null
      rank?: number | null
      percentile?: number | null
      xueji_rank?: number | null
      grade_rank?: number | null
    } | undefined
  > | null
  total_score?: number | null
  grade_rank?: number | null
}

interface RankBandEntry {
  total_type?: string
  class_num?: number | null
  class_label?: string | null
  mine?: boolean
  high_score: number
  critical: number
  weak: number
}

interface BandConfig {
  high_score_max: number
  critical_min: number
  critical_max: number
  weak_min: number
}

const DEFAULT_BAND_CONFIG: BandConfig = {
  high_score_max: 80,
  critical_min: 400,
  critical_max: 500,
  weak_min: 501,
}

interface BandTrendPoint {
  exam_id: number
  exam_name: string
  exam_date?: string | null
  high_score: number
  critical: number
  weak: number
}

interface TeacherClasses {
  target_class_high1: number | null
  target_class_high2: number | null
  target_class_high3: number | null
}

interface RankDistributionEntry {
  band: string
  [key: string]: string | number
}

interface RankMetricOption {
  value: string
  label: string
  kind: string
}

interface ExamChoice {
  id: number
  name: string
  grade: number
  exam_date?: string | null
}

interface RankFrequencyResponse {
  metric: string
  metric_label: string
  metric_kind: string
  class_num?: number | null
  exams: Array<{ id: number; name: string; exam_date?: string | null }>
  bins: Array<{ key: string; label: string; separator_after?: boolean }>
  rows: Array<Record<string, string | number | null>>
  metric_note?: string
}

interface RankRangeResponse {
  metric: string
  metric_label: string
  metric_kind: string
  rank_min: number
  rank_max: number
  class_num?: number | null
  rows: Array<{
    student_id: string
    name: string
    class_num?: number | null
    score?: number | null
    class_rank?: number | null
    year_rank?: number | null
  }>
  metric_note?: string
}

interface StudentListItem {
  student_id: string
  class_label?: string | null
}

type IssueTone = 'danger' | 'warning' | 'purple' | 'slate' | 'outline'

const SUBJECT_KEYS: { key: string; label: string }[] = [
  { key: '语文', label: '语' },
  { key: '数学', label: '数' },
  { key: '英语', label: '英' },
  { key: '物理', label: '物' },
  { key: '化学', label: '化' },
  { key: '生物', label: '生' },
  { key: '政治', label: '政' },
  { key: '历史', label: '史' },
  { key: '地理', label: '地' },
]

const BASE_AVERAGE_SUBJECTS = ['语文', '数学', '英语'] as const
const ELECTIVE_AVERAGE_SUBJECTS = ['物理', '化学', '生物', '政治', '历史', '地理'] as const
const ALL_AVERAGE_SUBJECTS = [
  ...BASE_AVERAGE_SUBJECTS,
  ...ELECTIVE_AVERAGE_SUBJECTS,
] as const

type AverageSummaryKind = '平均' | '最高' | '最低'
type AverageMetric =
  | { source: 'subject'; key: string }
  | { source: 'total'; key: string }
  | { source: 'rank'; key: string }

const RANK_DISTRIBUTION_COLORS = ['#4098ff', '#55d6c2', '#ff6b6b']

function classifyIssue(label: string): IssueTone {
  if (/退步|下滑/.test(label)) return 'danger'
  if (/波动/.test(label)) return 'warning'
  if (/偏科/.test(label)) return 'purple'
  if (/薄弱|低位/.test(label)) return 'slate'
  return 'outline'
}

function issueToneClass(tone: IssueTone): string {
  switch (tone) {
    case 'danger':
      return 'bg-danger-50 text-danger-500 border-transparent'
    case 'warning':
      return 'bg-warning-50 text-warning-500 border-transparent'
    case 'purple':
      return 'bg-purple-500 text-white border-transparent'
    case 'slate':
      return 'bg-slate-200 text-slate-700 border-transparent'
    case 'outline':
    default:
      return 'border-slate-200 text-slate-700 bg-white'
  }
}

function getInitial(name: string): string {
  if (!name) return '?'
  return name.trim().charAt(0)
}

function formatNumber(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toFixed(digits)
}

function formatTableNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return ''
  return Number(n)
    .toFixed(2)
    .replace(/\.00$/, '')
    .replace(/(\.\d)0$/, '$1')
}

function compareStudentId(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
) {
  const av = a == null ? '' : String(a)
  const bv = b == null ? '' : String(b)
  if (!av && !bv) return 0
  if (!av) return 1
  if (!bv) return -1
  return av.localeCompare(bv, undefined, { numeric: true })
}

function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return String(Math.round(Number(n)))
}

function formatPercentile(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const value = Math.abs(n) <= 1 ? n * 100 : n
  return `${value.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')}%`
}

function metricId(metric: AverageMetric): string {
  return `${metric.source}:${metric.key}`
}

function getTotalAverage(
  row: ClassAverage,
  key: string,
): number | null | undefined {
  if (key === '五门') {
    return row.total_averages?.['五门'] ?? row.total_averages?.['五门总分']
  }
  if (key === '九门') {
    return row.total_averages?.['九门'] ?? row.total_averages?.['九门总分']
  }
  if (key === '3+3') {
    return (
      row.total_averages?.['3+3'] ??
      row.total_averages?.['3+3总分'] ??
      row.total_averages?.['所有总分']
    )
  }
  return row.total_averages?.[key]
}

function getClassAverageMetricValue(
  row: ClassAverage,
  metric: AverageMetric,
): number | null | undefined {
  if (metric.source === 'subject') {
    if (metric.key.endsWith('_原始')) {
      const subject = metric.key.replace('_原始', '')
      return row.subject_averages?.[metric.key] ?? row.subject_averages?.[subject]
    }
    return row.subject_averages?.[metric.key]
  }
  if (metric.source === 'total') return getTotalAverage(row, metric.key)
  return null
}

function classRankKey(classType: string, classNum: number, totalKey: string) {
  return `${classType}::${classNum}::${totalKey}`
}

function numericAverageValues(rows: ClassAverage[], metric: AverageMetric): number[] {
  return rows
    .map((row) => getClassAverageMetricValue(row, metric))
    .filter(
      (value): value is number =>
        typeof value === 'number' && !Number.isNaN(value) && value !== 0,
    )
}

function getClassAverageMetrics(grade: number): AverageMetric[] {
  if (grade === 1) {
    return [
      ...ALL_AVERAGE_SUBJECTS.map((key) => ({ source: 'subject' as const, key })),
      { source: 'total', key: '主三门' },
      { source: 'rank', key: '主三门' },
      { source: 'total', key: '五门' },
      { source: 'rank', key: '五门' },
      { source: 'total', key: '九门' },
      { source: 'rank', key: '九门' },
    ]
  }

  return [
    ...BASE_AVERAGE_SUBJECTS.map((key) => ({ source: 'subject' as const, key })),
    ...ELECTIVE_AVERAGE_SUBJECTS.flatMap((subject) => [
      { source: 'subject' as const, key: `${subject}_原始` },
      { source: 'subject' as const, key: `${subject}_等级` },
    ]),
    { source: 'total', key: '+3' },
    { source: 'total', key: '主三门' },
    { source: 'rank', key: '主三门' },
    { source: 'total', key: '3+3' },
    { source: 'rank', key: '3+3' },
  ]
}

function getRankDistributionKeys(grade: number): string[] {
  return grade === 1 ? ['主三门', '五门', '九门'] : ['主三门', '+3', '3+3']
}

function getRankMetricOptions(
  grade: number,
  mode: 'range' | 'frequency',
): RankMetricOption[] {
  if (grade === 1) {
    return [
      ...ALL_AVERAGE_SUBJECTS.map((subject) => ({
        value: `subject:${subject}`,
        label: subject,
        kind: 'subject_percentile',
      })),
      { value: 'total:主三门', label: '主三门总分', kind: 'total_rank' },
      { value: 'total:五门', label: '五门总分', kind: 'total_rank' },
    ]
  }

  return [
    ...BASE_AVERAGE_SUBJECTS.map((subject) => ({
      value: `subject:${subject}`,
      label: subject,
      kind: 'subject_percentile',
    })),
    ...(mode === 'frequency'
      ? ELECTIVE_AVERAGE_SUBJECTS.map((subject) => ({
          value: `subject_grade:${subject}`,
          label: `${subject}等级分`,
          kind: 'subject_grade_score',
        }))
      : []),
    { value: 'total:主三门', label: '主三门总分', kind: 'total_rank' },
    { value: 'total:3+3', label: '3+3总分', kind: 'total_rank' },
  ]
}

function getStudentSubjectScore(
  row: StudentRow,
  subject: string,
  kind: 'raw' | 'grade' = 'raw',
): number | null {
  const source = kind === 'grade' ? row.subject_grade_scores : row.subject_scores
  const value = source?.[subject]
  return typeof value === 'number' && !Number.isNaN(value) ? value : null
}

function getStudentSubjectPercentile(row: StudentRow, subject: string): number | null {
  const value = row.subject_percentiles?.[subject]
  return typeof value === 'number' && !Number.isNaN(value) ? value : null
}

function getStudentTotalScore(row: StudentRow, totalType: string): number | null {
  if (totalType === '主三门') {
    return row.total_scores?.[totalType]?.score ?? row.total_score ?? null
  }
  return row.total_scores?.[totalType]?.score ?? null
}

function getStudentTotalPercentile(row: StudentRow, totalType: string): number | null {
  return row.total_scores?.[totalType]?.percentile ?? null
}

function getStudentTotalRank(row: StudentRow, totalType: string): number | null {
  if (totalType === '主三门') {
    return row.total_scores?.[totalType]?.rank ?? row.grade_rank ?? null
  }
  return row.total_scores?.[totalType]?.rank ?? null
}

function getStudentTotalXuejiRank(row: StudentRow, totalType: string): number | null {
  return row.total_scores?.[totalType]?.xueji_rank ?? null
}

function getStudentTotalGradeRank(row: StudentRow, totalType: string): number | null {
  if (totalType === '主三门') {
    return row.total_scores?.[totalType]?.grade_rank ?? row.grade_rank ?? null
  }
  return row.total_scores?.[totalType]?.grade_rank ?? null
}

function bandEntryLabel(row: RankBandEntry): string {
  return row.class_label ?? (row.class_num != null ? String(row.class_num) : '—')
}

/** 按总分类型分组；mine（我的教学班）置顶、其余按 label 排序。 */
function getRankBandsByType(
  rows: RankBandEntry[],
  grade: number,
): Array<{ key: string; label: string; rows: RankBandEntry[] }> {
  const keys = grade === 1 ? ['主三门'] : ['主三门', '3+3']
  return keys.map((key) => {
    const typeRows = rows
      .filter((row) => (row.total_type || '主三门') === key)
      .map((row) => ({ ...row, total_type: key }))
    // mine 置顶，其余按 label 自然序
    const sorted = typeRows.slice().sort((a, b) => {
      const am = a.mine ? 0 : 1
      const bm = b.mine ? 0 : 1
      if (am !== bm) return am - bm
      return bandEntryLabel(a).localeCompare(bandEntryLabel(b), undefined, {
        numeric: true,
      })
    })
    return {
      key,
      label: key === '主三门' ? '语数英三门' : '3+3总分',
      rows: sorted,
    }
  })
}

function getExamKpis(
  grade: number,
  stats: ExamStats,
  focusCount: number,
): Array<{
  icon: ReactNode
  title: string
  value: string
  hint: string
}> {
  const byType = stats.by_total_type || {}
  const main = byType['主三门']
  const five = byType['五门']
  const plus3 = byType['+3']
  const total33 = byType['3+3']
  const mainAvg = main?.avg ?? stats.avg_main_total
  const mainRankMin = main?.rank_min ?? stats.rank_min
  const mainRankMax = main?.rank_max ?? stats.rank_max

  if (grade === 1) {
    return [
      {
        icon: <BookOpen className="h-4 w-4" />,
        title: '主三门班均',
        value: formatNumber(mainAvg),
        hint: main?.count ? `语数英排名主口径 · ${main.count} 人` : '语数英总分排名主口径',
      },
      {
        icon: <TrendingUp className="h-4 w-4" />,
        title: '主三门名次区间',
        value:
          mainRankMin != null || mainRankMax != null
            ? `${formatInt(mainRankMin)} - ${formatInt(mainRankMax)}`
            : '—',
        hint: '本班学籍排名',
      },
      {
        icon: <Hash className="h-4 w-4" />,
        title: '五门班均',
        value: formatNumber(five?.avg),
        hint: '语数英物化总分辅助口径',
      },
      {
        icon: <AlertCircle className="h-4 w-4" />,
        title: '重点关注',
        value: String(focusCount),
        hint: '主三门 + 学籍排名口径',
      },
    ]
  }

  return [
    {
      icon: <BookOpen className="h-4 w-4" />,
      title: '主三门班均',
      value: formatNumber(mainAvg),
      hint: main?.count ? `语数英总分 · ${main.count} 人` : '语数英总分',
    },
    {
      icon: <TrendingUp className="h-4 w-4" />,
      title: '+3班均',
      value: formatNumber(plus3?.avg),
      hint: '选科三门总分',
    },
    {
      icon: <Hash className="h-4 w-4" />,
      title: '3+3班均',
      value: formatNumber(total33?.avg),
      hint: '语数英 + 选科总分',
    },
    {
      icon: <AlertCircle className="h-4 w-4" />,
      title: '重点关注',
      value: String(focusCount),
      hint: '主三门 + 学籍排名口径',
    },
  ]
}

function buildClassAverageRanks(rows: ClassAverage[], metrics: AverageMetric[]) {
  const groups = groupClassAverages(rows)
  const rankMap = new Map<string, number>()
  const rankKeys = metrics
    .filter((metric): metric is { source: 'rank'; key: string } => metric.source === 'rank')
    .map((metric) => metric.key)

  groups.forEach((group) => {
    rankKeys.forEach((totalKey) => {
      const sorted = group.rows
        .map((row) => ({
          row,
          value: getTotalAverage(row, totalKey),
        }))
        .filter(
          (entry): entry is { row: ClassAverage; value: number } =>
            typeof entry.value === 'number' &&
            !Number.isNaN(entry.value) &&
            entry.value !== 0,
        )
        .sort((a, b) => b.value - a.value)

      sorted.forEach((entry, index) => {
        rankMap.set(
          classRankKey(group.type, entry.row.class_num, totalKey),
          index + 1,
        )
      })
    })
  })

  return rankMap
}

function getRankValue(
  row: ClassAverage,
  classType: string,
  metric: AverageMetric,
  rankMap: Map<string, number>,
): number | null {
  if (metric.source !== 'rank') return null
  return rankMap.get(classRankKey(classType, row.class_num, metric.key)) ?? null
}

function groupClassAverages(rows: ClassAverage[]) {
  const groupMap = new Map<string, ClassAverage[]>()

  rows.forEach((row) => {
    const type = row.class_type || '未分组'
    if (!groupMap.has(type)) groupMap.set(type, [])
    groupMap.get(type)?.push(row)
  })

  return Array.from(groupMap.entries()).map(([type, groupRows]) => ({
    type,
    rows: [...groupRows].sort((a, b) => a.class_num - b.class_num),
  }))
}

function getClassAverageSummaryValue(
  rows: ClassAverage[],
  metric: AverageMetric,
  kind: AverageSummaryKind,
): number | null {
  if (metric.source === 'rank') return null
  const values = numericAverageValues(rows, metric)
  if (!values.length) return null
  if (kind === '最高') return Math.max(...values)
  if (kind === '最低') return Math.min(...values)
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function exportClassAverageCsv(rows: ClassAverage[], examName: string, grade: number) {
  const metrics = getClassAverageMetrics(grade)
  const rankMap = buildClassAverageRanks(rows, metrics)
  const headers = [
    '班级类型',
    '班级',
    '班主任',
    ...metrics.map((metric) => {
      if (metric.source === 'rank') return `${metric.key}排名`
      if (metric.source === 'total') return `${metric.key}分数`
      return metric.key.replace('_', '')
    }),
  ]
  const lines = [
    headers,
    ...groupClassAverages(rows).flatMap((group) =>
      group.rows.map((row) =>
        [
          group.type,
          row.class_label || `${String(row.class_num).padStart(2, '0')}班`,
          row.teacher_name || '',
          ...metrics.map((metric) =>
            metric.source === 'rank'
              ? String(getRankValue(row, group.type, metric, rankMap) ?? '')
              : formatTableNumber(getClassAverageMetricValue(row, metric)),
          ),
        ].map((cell) => `"${String(cell).replace(/"/g, '""')}"`),
      ),
    ),
  ]
  const csv = lines.map((line) => line.join(',')).join('\n')
  const blob = new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${examName || '班级均分'}-班级均分.csv`
  link.click()
  URL.revokeObjectURL(url)
}

function heatmapClass(score: number | null | undefined, min: number, max: number): string {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return 'bg-slate-50 text-slate-400'
  }
  if (max <= min) return 'bg-white text-slate-700'
  // 分数越高 = 颜色越绿；分数越低 = 颜色越红
  const ratio = (score - min) / (max - min)
  // 反转后用 0..1 上色：0 深绿 → 1 深红
  const inv = 1 - ratio
  if (inv <= 0.2) return 'bg-green-200 text-green-900'
  if (inv <= 0.4) return 'bg-green-50 text-green-800'
  if (inv <= 0.6) return 'bg-white text-slate-700'
  if (inv <= 0.8) return 'bg-red-50 text-red-700'
  return 'bg-red-200 text-red-900'
}

type SortDirection = 'asc' | 'desc' | null

export default function ExamDetailPage() {
  const params = useParams<{ id: string }>()
  const examId = params?.id
  const { current, currentClass, scopeParam } = useClassScope()

  const [exam, setExam] = useState<ExamDetail | null>(null)
  const [classAverages, setClassAverages] = useState<ClassAverage[]>([])
  const [stats, setStats] = useState<ExamStats>({})
  const [students, setStudents] = useState<StudentRow[]>([])
  const [rankBands, setRankBands] = useState<RankBandEntry[]>([])
  const [rankDistribution, setRankDistribution] = useState<RankDistributionEntry[]>([])
  const [focusList, setFocusList] = useState<FocusStudent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 学生 → 所属教学班 label 映射（用于成绩矩阵的教学班徽章列）
  const [labelByStudentId, setLabelByStudentId] = useState<Map<string, string>>(
    () => new Map(),
  )

  const [focusQuery, setFocusQuery] = useState('')
  const [studentQuery, setStudentQuery] = useState('')
  const [studentSortKey, setStudentSortKey] = useState<string | null>(null)
  const [studentSortDir, setStudentSortDir] = useState<SortDirection>(null)

  // 重点关注段位阈值（可自定义）
  const [bandConfig, setBandConfig] = useState<BandConfig>(DEFAULT_BAND_CONFIG)
  const [reloadKey, setReloadKey] = useState(0)
  const [bandEditorOpen, setBandEditorOpen] = useState(false)
  const [bandDraft, setBandDraft] = useState<BandConfig>(DEFAULT_BAND_CONFIG)
  const [savingBand, setSavingBand] = useState(false)
  const [bandError, setBandError] = useState<string | null>(null)
  // 受控 tab：保存段位触发 refetch（含整页 loading）后仍停留在当前 tab
  const [activeTab, setActiveTab] = useState('averages')

  // 排名频次 / 排名区间筛选
  const [rankClass, setRankClass] = useState<number | null | undefined>(undefined)
  const [examChoices, setExamChoices] = useState<ExamChoice[]>([])
  const [frequencyMetric, setFrequencyMetric] = useState('subject:语文')
  const [frequencyExamIds, setFrequencyExamIds] = useState<number[]>([])
  const [frequencyData, setFrequencyData] = useState<RankFrequencyResponse | null>(null)
  const [frequencyLoading, setFrequencyLoading] = useState(false)
  const [rangeExamId, setRangeExamId] = useState<number | null>(null)
  const [rangeMetric, setRangeMetric] = useState('subject:语文')
  const [rangeMin, setRangeMin] = useState(1)
  const [rangeMax, setRangeMax] = useState(100)
  const [rangeData, setRangeData] = useState<RankRangeResponse | null>(null)
  const [rangeLoading, setRangeLoading] = useState(false)

  // 历次段位趋势
  const [teacherInfo, setTeacherInfo] = useState<TeacherClasses | null>(null)
  const [teacherLoaded, setTeacherLoaded] = useState(false)
  const [trendClass, setTrendClass] = useState<number | null | undefined>(undefined)
  const [bandTrend, setBandTrend] = useState<BandTrendPoint[]>([])
  const [trendClasses, setTrendClasses] = useState<number[]>([])

  useEffect(() => {
    if (!examId) return
    let cancelled = false
    setLoading(true)
    setError(null)

    const scope = scopeParam()
    const tcParam = scope.teaching_class_id
      ? `?teaching_class_id=${scope.teaching_class_id}`
      : ''
    const focusTcParam = scope.teaching_class_id
      ? `?teaching_class_id=${scope.teaching_class_id}`
      : ''

    const examReq = fetch(`/api/exams/${examId}${tcParam}`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return (await r.json()) as ExamApiResponse
    })
    const focusReq = fetch(`/api/focus-list/${examId}${focusTcParam}`)
      .then(async (r) => (r.ok ? await r.json() : { focus_list: [] }))
      .catch(() => ({ focus_list: [] }))

    Promise.all([examReq, focusReq])
      .then(([examData, focusData]) => {
        if (cancelled) return
        setExam(examData.exam)
        setClassAverages(examData.class_averages || [])
        setStats(examData.stats || {})
        setStudents(examData.students || [])
        setRankBands(examData.rank_bands || [])
        setBandConfig(examData.band_config || DEFAULT_BAND_CONFIG)
        setRankDistribution(examData.rank_distribution || [])
        // focusData 来自 /api/focus-list；examData.focus_list 兼容（如果后端某天合并）
        const list: FocusStudent[] =
          (focusData?.focus_list as FocusStudent[]) || examData.focus_list || []
        setFocusList(list)
      })
      .catch((err) => {
        if (cancelled) return
        console.error(err)
        setError(err?.message || '加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // scope 变化（current 教学班）即重新拉取；reloadKey 为段位阈值保存触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examId, reloadKey, current])

  // 拉取「学生 → 教学班 label」映射，用于成绩矩阵的教学班徽章列。
  // 选定具体教学班时，矩阵内学生均属该班，直接用 currentClass.label；
  // 选「全部」时用 /api/students 拉回每生 label。
  useEffect(() => {
    const grade = exam?.grade
    if (!grade) return
    let cancelled = false
    if (current !== 'all') {
      // 选定教学班：直接置为当前班 label
      if (!cancelled) {
        setLabelByStudentId(new Map())
      }
      return
    }
    fetch(`/api/students?grade=${grade}`)
      .then((r) => (r.ok ? r.json() : { students: [] }))
      .then((data) => {
        if (cancelled) return
        const map = new Map<string, string>()
        ;(data.students as StudentListItem[]).forEach((s) => {
          if (s.class_label) map.set(s.student_id, s.class_label)
        })
        setLabelByStudentId(map)
      })
      .catch(() => {
        if (!cancelled) setLabelByStudentId(new Map())
      })
    return () => {
      cancelled = true
    }
  }, [exam?.grade, current])

  /** 某学生的教学班徽章文本：优先用映射，否则回落到选中的教学班 label，再回落到 class_num。 */
  function studentBadge(row: StudentRow): string | null {
    const fromMap = labelByStudentId.get(row.student_id)
    if (fromMap) return formatClassChip(fromMap)
    if (current !== 'all' && currentClass) return formatClassChip(currentClass.label)
    if (row.class_num != null) return `${row.class_num}班`
    return null
  }

  useEffect(() => {
    if (!exam) return
    const frequencyOptions = getRankMetricOptions(exam.grade, 'frequency')
    const rangeOptions = getRankMetricOptions(exam.grade, 'range')
    setFrequencyMetric(frequencyOptions[0]?.value || 'subject:语文')
    setRangeMetric(rangeOptions[0]?.value || 'subject:语文')
    setRangeExamId(exam.id)
  }, [exam?.id, exam?.grade])

  // 拉取本班绑定（用于趋势图默认选中本班）
  useEffect(() => {
    let cancelled = false
    fetch('/api/teacher')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: TeacherClasses | null) => {
        if (!cancelled && d) setTeacherInfo(d)
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setTeacherLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const grade = exam?.grade
    if (!grade || !teacherLoaded || rankClass !== undefined) return
    const bound =
      grade === 1
        ? teacherInfo?.target_class_high1
        : grade === 2
          ? teacherInfo?.target_class_high2
          : teacherInfo?.target_class_high3
    setRankClass(bound ?? null)
  }, [exam?.grade, teacherLoaded, teacherInfo, rankClass])

  useEffect(() => {
    if (!exam?.grade) return
    let cancelled = false
    fetch(`/api/exams?grade=${exam.grade}`)
      .then((r) => (r.ok ? r.json() : { exams: [] }))
      .then((data) => {
        if (cancelled) return
        const choices = (data.exams || []) as ExamChoice[]
        setExamChoices(choices)
        const defaultIds = choices.slice(0, 5).map((item) => item.id)
        setFrequencyExamIds(defaultIds.length ? defaultIds : [exam.id])
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [exam?.grade, exam?.id])

  useEffect(() => {
    if (!exam?.grade || frequencyExamIds.length === 0 || rankClass === undefined) return
    let cancelled = false
    setFrequencyLoading(true)
    const params = new URLSearchParams({
      grade: String(exam.grade),
      metric: frequencyMetric,
      exam_ids: frequencyExamIds.join(','),
    })
    if (rankClass != null) params.set('class_num', String(rankClass))
    fetch(`/api/rank-frequency?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: RankFrequencyResponse | null) => {
        if (!cancelled) setFrequencyData(data)
      })
      .catch(() => {
        if (!cancelled) setFrequencyData(null)
      })
      .finally(() => {
        if (!cancelled) setFrequencyLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [exam?.grade, frequencyMetric, frequencyExamIds, rankClass])

  useEffect(() => {
    if (!rangeExamId || !rangeMetric || rankClass === undefined) return
    let cancelled = false
    setRangeLoading(true)
    const params = new URLSearchParams({
      exam_id: String(rangeExamId),
      metric: rangeMetric,
      rank_min: String(rangeMin),
      rank_max: String(rangeMax),
    })
    if (rankClass != null) params.set('class_num', String(rankClass))
    fetch(`/api/rank-range?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: RankRangeResponse | null) => {
        if (!cancelled) setRangeData(data)
      })
      .catch(() => {
        if (!cancelled) setRangeData(null)
      })
      .finally(() => {
        if (!cancelled) setRangeLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [rangeExamId, rangeMetric, rangeMin, rangeMax, rankClass])

  // 初始化默认班级（本班）+ 拉取历次段位趋势；改阈值（reloadKey）后同步刷新
  useEffect(() => {
    const grade = exam?.grade
    if (!grade || !teacherLoaded) return

    // 首次：把默认班级设为本班（无绑定则全年级）
    if (trendClass === undefined) {
      const bound =
        grade === 1
          ? teacherInfo?.target_class_high1
          : grade === 2
            ? teacherInfo?.target_class_high2
            : teacherInfo?.target_class_high3
      setTrendClass(bound ?? null)
      return
    }

    let cancelled = false
    const q = trendClass == null ? '' : `&class_num=${trendClass}`
    fetch(`/api/band-trend?grade=${grade}${q}`)
      .then((r) => (r.ok ? r.json() : { series: [], available_classes: [] }))
      .then((d) => {
        if (cancelled) return
        setBandTrend(d.series || [])
        setTrendClasses(d.available_classes || [])
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [exam?.grade, teacherLoaded, teacherInfo, trendClass, reloadKey])

  function openBandEditor() {
    setBandDraft(bandConfig)
    setBandError(null)
    setBandEditorOpen(true)
  }

  async function saveBandConfig() {
    // 前端先做与后端一致的基本校验
    const { high_score_max, critical_min, critical_max, weak_min } = bandDraft
    if (
      [high_score_max, critical_min, critical_max, weak_min].some(
        (n) => !Number.isFinite(n) || n < 1,
      )
    ) {
      setBandError('各项排名必须为正整数')
      return
    }
    if (critical_min > critical_max) {
      setBandError('临界段下界不能大于上界')
      return
    }
    setSavingBand(true)
    setBandError(null)
    try {
      const res = await fetch('/api/analysis-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bandDraft),
      })
      if (!res.ok) {
        const msg = await res.json().catch(() => null)
        throw new Error(msg?.detail || `保存失败（HTTP ${res.status}）`)
      }
      setBandEditorOpen(false)
      // 重新拉取考试详情，让柱状图按新口径重算
      setReloadKey((k) => k + 1)
    } catch (err) {
      setBandError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSavingBand(false)
    }
  }

  const bandLabels = {
    high_score: `高分段(1-${bandConfig.high_score_max})`,
    critical: `临界段(${bandConfig.critical_min}-${bandConfig.critical_max})`,
    weak: `薄弱段(≥${bandConfig.weak_min})`,
  }

  // 重点关注：搜索过滤
  const filteredFocus = useMemo(() => {
    const q = focusQuery.trim().toLowerCase()
    if (!q) return focusList
    return focusList.filter(
      (s) =>
        (s.name || '').toLowerCase().includes(q) ||
        (s.student_id || '').toLowerCase().includes(q),
    )
  }, [focusList, focusQuery])

  // 学生成绩：科目 min/max（用于热力图）
  const subjectRange = useMemo(() => {
    const range: Record<string, { min: number; max: number }> = {}
    SUBJECT_KEYS.forEach(({ key }) => {
      const values = students
        .map((s) => s.subject_scores?.[key])
        .filter((v): v is number => typeof v === 'number' && !Number.isNaN(v))
      if (values.length) {
        range[key] = { min: Math.min(...values), max: Math.max(...values) }
      }
    })
    return range
  }, [students])

  const examKpis = useMemo(
    () => (exam ? getExamKpis(exam.grade, stats, focusList.length) : []),
    [exam, stats, focusList.length],
  )

  const frequencyMetricOptions = useMemo(
    () => (exam ? getRankMetricOptions(exam.grade, 'frequency') : []),
    [exam],
  )
  const rangeMetricOptions = useMemo(
    () => (exam ? getRankMetricOptions(exam.grade, 'range') : []),
    [exam],
  )
  const rankClasses = useMemo(() => {
    const values = new Set<number>()
    students.forEach((student) => {
      if (student.class_num != null) values.add(student.class_num)
    })
    return Array.from(values).sort((a, b) => a - b)
  }, [students])

  // 学生成绩：过滤 + 排序
  const visibleStudents = useMemo(() => {
    const q = studentQuery.trim().toLowerCase()
    let list = q
      ? students.filter(
          (s) =>
            (s.name || '').toLowerCase().includes(q) ||
            (s.student_id || '').toLowerCase().includes(q),
        )
      : students.slice()

    if (studentSortKey && studentSortDir) {
      const dir = studentSortDir === 'asc' ? 1 : -1
      list = list.slice().sort((a, b) => {
        const av = getSortValue(a, studentSortKey)
        const bv = getSortValue(b, studentSortKey)
        if (av === null && bv === null) return 0
        if (av === null) return 1
        if (bv === null) return -1
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
        return String(av).localeCompare(String(bv)) * dir
      })
    } else {
      list = list.slice().sort((a, b) => compareStudentId(a.student_id, b.student_id))
    }
    return list
  }, [students, studentQuery, studentSortKey, studentSortDir])

  function toggleSort(key: string) {
    if (studentSortKey !== key) {
      setStudentSortKey(key)
      setStudentSortDir('asc')
      return
    }
    if (studentSortDir === 'asc') setStudentSortDir('desc')
    else if (studentSortDir === 'desc') {
      setStudentSortDir(null)
      setStudentSortKey(null)
    } else setStudentSortDir('asc')
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-72" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
        <Skeleton className="h-10 w-80" />
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !exam) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 py-16 text-center">
          <AlertCircle className="h-10 w-10 text-danger-500" />
          <div className="text-base font-medium text-slate-900">加载失败</div>
          <div className="text-sm text-slate-500">
            {error || '未找到该考试'}
          </div>
          <Link href="/">
            <Button variant="outline" size="sm">
              <ChevronLeft className="mr-1 h-4 w-4" /> 返回首页
            </Button>
          </Link>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-3">
        <Link
          href="/"
          className="inline-flex items-center text-sm text-slate-500 hover:text-slate-900"
        >
          <ChevronLeft className="mr-1 h-4 w-4" /> 返回
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">{exam.name}</h1>
            <p className="mt-1 text-sm text-slate-500">
              分析时间口径来自 EXAM_ORDER
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* 教学班范围选择器：切换后整页按所选教学班重新统计 */}
            <ClassScopePicker grade={exam.grade} compact />
            <Badge variant="default">{formatGradeLabel(exam.grade)}</Badge>
            <Badge variant="secondary">{exam.exam_date || '—'}</Badge>
            {exam.exam_type ? (
              <Badge variant="outline">{exam.exam_type}</Badge>
            ) : null}
          </div>
        </div>
      </div>

      {/* KPI */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {examKpis.map((kpi) => (
          <KpiCard
            key={kpi.title}
            icon={kpi.icon}
            title={kpi.title}
            value={kpi.value}
            hint={kpi.hint}
          />
        ))}
      </div>

      {rankDistribution.length > 0 ? (
        <Card>
          <CardContent className="px-4 py-3">
            <RankDistributionChart
              data={rankDistribution}
              keys={getRankDistributionKeys(exam.grade)}
            />
          </CardContent>
        </Card>
      ) : null}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="flex h-auto max-w-full justify-start overflow-x-auto [-webkit-overflow-scrolling:touch] [&>button]:shrink-0">
          <TabsTrigger value="averages">
            班级均分表
          </TabsTrigger>
          <TabsTrigger value="scores">
            学生成绩明细表
          </TabsTrigger>
          <TabsTrigger value="bands">
            班级名次段位表
          </TabsTrigger>
          <TabsTrigger value="frequency">
            排名频次统计
          </TabsTrigger>
          <TabsTrigger value="range">
            排名区间筛选
          </TabsTrigger>
          <TabsTrigger value="focus">
            <AlertCircle className="mr-1.5 h-4 w-4" /> 重点关注
          </TabsTrigger>
        </TabsList>

        <TabsContent value="averages">
          {classAverages.length > 0 ? (
            <Card className="overflow-hidden">
              <CardHeader className="flex flex-row items-center justify-end space-y-0 border-b border-slate-200 bg-white px-4 py-3">
                <Button
                  size="sm"
                  className="h-8 gap-1.5"
                  onClick={() =>
                    exportClassAverageCsv(
                      classAverages,
                      exam?.name || '',
                      exam?.grade || 1,
                    )
                  }
                >
                  <Download className="h-4 w-4" />
                  导出数据
                </Button>
              </CardHeader>
              <CardContent className="p-4">
                <ClassAverageDingTable rows={classAverages} grade={exam.grade} />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent>
                <EmptyState
                  icon={<BarChart3 className="h-8 w-8 text-slate-400" />}
                  title="该考试无班级均分表"
                  desc="请先上传对应考试的班级均分 Excel。"
                />
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Tab 1: Focus */}
        <TabsContent value="focus">
          <Card>
            <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <CardTitle>重点关注名单</CardTitle>
                <CardDescription>
                  基于主三门 + 学籍排名口径筛选；五门作辅证，九门不进。
                </CardDescription>
              </div>
              <div className="relative w-full sm:w-72">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  value={focusQuery}
                  onChange={(e) => setFocusQuery(e.target.value)}
                  placeholder="按姓名 / 学号搜索"
                  className="pl-9"
                />
              </div>
            </CardHeader>
            <CardContent>
              {filteredFocus.length === 0 ? (
                <EmptyState
                  icon={<AlertCircle className="h-8 w-8 text-success-500" />}
                  title={focusQuery ? '没有匹配的学生' : '暂无重点关注'}
                  desc={
                    focusQuery
                      ? '换个关键词试试'
                      : '本场考试主三门 + 学籍排名口径下无需特别关注。'
                  }
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-32">学号</TableHead>
                      <TableHead>学生</TableHead>
                      <TableHead className="w-24">教学班</TableHead>
                      <TableHead>问题</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredFocus.map((s) => {
                      const issues =
                        s.issues && s.issues.length
                          ? s.issues
                          : s.issue
                          ? [s.issue]
                          : []
                      const focusBadge =
                        s.class_label ||
                        (s.class_num != null ? `${s.class_num}班` : null)
                      return (
                        <TableRow key={s.student_id}>
                          <TableCell className="font-mono text-xs text-slate-600">
                            {s.student_id}
                          </TableCell>
                          <TableCell>
                            <Link
                              href={`/student/${s.student_id}`}
                              className="inline-flex items-center gap-2 text-slate-900 hover:text-brand-600"
                            >
                              <Avatar className="h-7 w-7">
                                <AvatarFallback className="bg-brand-50 text-xs text-brand-700">
                                  {getInitial(s.name)}
                                </AvatarFallback>
                              </Avatar>
                              <span className="font-medium">{s.name}</span>
                            </Link>
                          </TableCell>
                          <TableCell className="text-sm text-slate-600">
                            {focusBadge ? (
                              <Badge variant="secondary" className="font-normal">
                                {focusBadge}
                              </Badge>
                            ) : (
                              '—'
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {issues.length === 0 ? (
                                <span className="text-sm text-slate-400">—</span>
                              ) : (
                                issues.map((label, i) => (
                                  <Badge
                                    key={i}
                                    variant="outline"
                                    className={cn(
                                      'border',
                                      issueToneClass(classifyIssue(label)),
                                    )}
                                  >
                                    {label}
                                  </Badge>
                                ))
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 2: Student scores */}
        <TabsContent value="scores">
          <Card>
            <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <CardTitle>学生成绩明细</CardTitle>
                <CardDescription>
                  分数按各科相对名次配色，缺考显示「—」。
                </CardDescription>
              </div>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="relative w-full sm:w-72">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <Input
                    value={studentQuery}
                    onChange={(e) => setStudentQuery(e.target.value)}
                    placeholder="按姓名 / 学号搜索"
                    className="pl-9"
                    disabled={students.length === 0}
                  />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {students.length === 0 ? (
                <EmptyState
                  icon={<Users className="h-8 w-8 text-slate-400" />}
                  title="学生成绩明细暂不可用"
                  desc="后端 /api/exams/{id} 暂未返回完整学生分数列表。"
                />
              ) : (
                <>
                  {/* 桌面：宽表；手机：卡片 */}
                  <div className="hidden md:block">
                    <StudentScoresTable
                      grade={exam.grade}
                      rows={visibleStudents}
                      subjectRange={subjectRange}
                      studentSortKey={studentSortKey}
                      studentSortDir={studentSortDir}
                      onSort={toggleSort}
                      badgeOf={studentBadge}
                    />
                  </div>
                  <StudentScoreMobileCards
                    grade={exam.grade}
                    rows={visibleStudents}
                    badgeOf={studentBadge}
                  />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 3: Rank bands */}
        <TabsContent value="bands">
          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <CardTitle>分数段分布</CardTitle>
                  <CardDescription>
                    按学籍排名口径划分：高分段 1-{bandConfig.high_score_max}、临界段{' '}
                    {bandConfig.critical_min}-{bandConfig.critical_max}、薄弱段 第{' '}
                    {bandConfig.weak_min} 名及以后。「我的教学班」高亮并置顶。
                  </CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={openBandEditor}>
                  自定义段位
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {bandEditorOpen && (
                <div className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-1 text-sm font-medium text-slate-800">
                    自定义重点关注段位（按学籍排名）
                  </div>
                  <p className="mb-3 text-xs text-slate-500">
                    设置对全局所有考试和 AI 问答生效。薄弱段下界可独立设置，与临界段上界之间可留空档。
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div className="space-y-1">
                      <label className="text-xs text-slate-600">高分段上界</label>
                      <Input
                        type="number"
                        min={1}
                        value={bandDraft.high_score_max}
                        onChange={(e) =>
                          setBandDraft((d) => ({ ...d, high_score_max: Number(e.target.value) }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-600">临界段下界</label>
                      <Input
                        type="number"
                        min={1}
                        value={bandDraft.critical_min}
                        onChange={(e) =>
                          setBandDraft((d) => ({ ...d, critical_min: Number(e.target.value) }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-600">临界段上界</label>
                      <Input
                        type="number"
                        min={1}
                        value={bandDraft.critical_max}
                        onChange={(e) =>
                          setBandDraft((d) => ({ ...d, critical_max: Number(e.target.value) }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-600">薄弱段下界</label>
                      <Input
                        type="number"
                        min={1}
                        value={bandDraft.weak_min}
                        onChange={(e) =>
                          setBandDraft((d) => ({ ...d, weak_min: Number(e.target.value) }))
                        }
                      />
                    </div>
                  </div>
                  {bandError && (
                    <div className="mt-2 text-sm text-danger-500">{bandError}</div>
                  )}
                  <div className="mt-3 flex items-center justify-end gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setBandEditorOpen(false)}
                      disabled={savingBand}
                    >
                      取消
                    </Button>
                    <Button size="sm" onClick={saveBandConfig} disabled={savingBand}>
                      {savingBand ? '保存中…' : '保存并应用'}
                    </Button>
                  </div>
                </div>
              )}
              {rankBands.length === 0 ? (
                <EmptyState
                  icon={<BarChart3 className="h-8 w-8 text-slate-400" />}
                  title="该考试无分数段数据"
                  desc="后端未返回 rank_bands 字段；可在数据入库后再回来查看。"
                />
              ) : (
                <div className="grid gap-4 lg:grid-cols-2">
                  {getRankBandsByType(rankBands, exam.grade).map((group) =>
                    group.rows.length > 0 ? (
                      <div key={group.key} className="rounded-sm border border-slate-200 p-3">
                        <div className="mb-2 text-sm font-semibold text-slate-900">
                          {group.label}
                        </div>
                        <RankBandByClassTable
                          data={group.rows}
                          labels={bandLabels}
                        />
                      </div>
                    ) : null,
                  )}
                </div>
              )}

              {/* 历次段位人数趋势 */}
              <div className="mt-6 border-t border-slate-100 pt-4">
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">历次段位人数趋势</div>
                    <div className="text-xs text-slate-500">
                      同一年级历次考试中各段人数变化（按考试时间排序）；修改上方阈值后趋势同步更新。
                    </div>
                  </div>
                  <Select
                    value={trendClass == null ? 'all' : String(trendClass)}
                    onValueChange={(v) => setTrendClass(v === 'all' ? null : Number(v))}
                  >
                    <SelectTrigger className="w-32 shrink-0">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全年级</SelectItem>
                      {trendClasses.map((c) => (
                        <SelectItem key={c} value={String(c)}>
                          {c} 班
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {bandTrend.length === 0 ? (
                  <div className="rounded-md border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-400">
                    暂无历次考试数据
                  </div>
                ) : (
                  <BandTrendChart data={bandTrend} labels={bandLabels} />
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="frequency">
          <Card>
            <CardHeader>
              <CardTitle>排名频次统计</CardTitle>
              <CardDescription>
                单科按年级百分位五等分；高二/高三选考科目按 70、67、64、61、58、55、52、49、46、43、40 精确等级分统计；总分按 40 名一档统计。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <RankScopeControls
                rankClass={rankClass}
                classes={rankClasses}
                onClassChange={setRankClass}
              />
              <div className="space-y-2">
                <div className="text-xs font-medium text-slate-500">选择考试（可多选）</div>
                <div className="flex flex-wrap gap-2">
                  {examChoices.map((choice) => {
                    const checked = frequencyExamIds.includes(choice.id)
                    return (
                      <label
                        key={choice.id}
                        className={cn(
                          'inline-flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs',
                          checked
                            ? 'border-brand-300 bg-brand-50 text-brand-700'
                            : 'border-slate-200 bg-white text-slate-600',
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(event) => {
                            setFrequencyExamIds((ids) =>
                              event.target.checked
                                ? [...ids, choice.id]
                                : ids.filter((id) => id !== choice.id),
                            )
                          }}
                          className="h-3.5 w-3.5 accent-blue-600"
                        />
                        <span>{choice.name}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
              <MetricButtonGroup
                options={frequencyMetricOptions}
                value={frequencyMetric}
                onChange={setFrequencyMetric}
              />
              {frequencyLoading ? (
                <Skeleton className="h-64 w-full" />
              ) : frequencyData && frequencyData.rows.length > 0 ? (
                <RankFrequencyTable data={frequencyData} />
              ) : (
                <EmptyState
                  icon={<Hash className="h-8 w-8 text-slate-400" />}
                  title="暂无排名频次数据"
                  desc="请至少选择一场考试，并确认该指标在已导入数据中存在。"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="range">
          <Card>
            <CardHeader>
              <CardTitle>排名区间筛选</CardTitle>
              <CardDescription>
                总分使用已有学籍/年级排名；单科使用年级百分位换算年级排名后筛选。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <RankScopeControls
                rankClass={rankClass}
                classes={rankClasses}
                onClassChange={setRankClass}
              />
              <div className="grid gap-3 lg:grid-cols-[minmax(220px,360px)_1fr]">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-500">选择考试</label>
                  <Select
                    value={rangeExamId == null ? undefined : String(rangeExamId)}
                    onValueChange={(value) => setRangeExamId(Number(value))}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="选择考试" />
                    </SelectTrigger>
                    <SelectContent>
                      {examChoices.map((choice) => (
                        <SelectItem key={choice.id} value={String(choice.id)}>
                          {choice.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-slate-500">筛选年级排名</label>
                  <div className="flex items-center gap-2">
                    <Input
                      type="number"
                      min={1}
                      value={rangeMin}
                      onChange={(event) => setRangeMin(Math.max(1, Number(event.target.value) || 1))}
                      className="w-28"
                    />
                    <span className="text-sm text-slate-500">至</span>
                    <Input
                      type="number"
                      min={1}
                      value={rangeMax}
                      onChange={(event) => setRangeMax(Math.max(1, Number(event.target.value) || 1))}
                      className="w-28"
                    />
                  </div>
                </div>
              </div>
              <MetricButtonGroup
                options={rangeMetricOptions}
                value={rangeMetric}
                onChange={setRangeMetric}
              />
              {rangeLoading ? (
                <Skeleton className="h-64 w-full" />
              ) : rangeData && rangeData.rows.length > 0 ? (
                <RankRangeTable data={rangeData} />
              ) : (
                <EmptyState
                  icon={<Search className="h-8 w-8 text-slate-400" />}
                  title="没有匹配学生"
                  desc="换一个考试、指标或排名区间再试。"
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function RankDistributionChart({
  data,
  keys,
}: {
  data: RankDistributionEntry[]
  keys: string[]
}) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 18, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="band"
            interval="preserveStartEnd"
            tick={{ fontSize: 11, fill: '#64748b' }}
            stroke="#e5e7eb"
          />
          <YAxis
            allowDecimals={false}
            tick={{ fontSize: 11, fill: '#64748b' }}
            stroke="#e5e7eb"
          />
          <Tooltip
            contentStyle={{
              border: '1px solid #e2e8f0',
              borderRadius: 6,
              boxShadow: '0 8px 24px rgb(15 23 42 / 0.08)',
              fontSize: 12,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {keys.map((key, index) => (
            <Bar
              key={key}
              dataKey={key}
              fill={RANK_DISTRIBUTION_COLORS[index % RANK_DISTRIBUTION_COLORS.length]}
              name={`${key}总分`}
              radius={[2, 2, 0, 0]}
              maxBarSize={18}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function RankScopeControls({
  rankClass,
  classes,
  onClassChange,
}: {
  rankClass: number | null | undefined
  classes: number[]
  onClassChange: (value: number | null) => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-1">
        <label className="text-xs font-medium text-slate-500">统计范围</label>
        <Select
          value={rankClass == null ? 'all' : String(rankClass)}
          onValueChange={(value) => onClassChange(value === 'all' ? null : Number(value))}
        >
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全年级</SelectItem>
            {classes.map((classNum) => (
              <SelectItem key={classNum} value={String(classNum)}>
                {classNum} 班
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

function MetricButtonGroup({
  options,
  value,
  onChange,
}: {
  options: RankMetricOption[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-slate-500">选择指标</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={option.value === value ? 'default' : 'outline'}
            className="h-8 px-2.5 text-xs"
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

function RankFrequencyTable({ data }: { data: RankFrequencyResponse }) {
  const minWidth =
    data.metric_kind === 'subject_grade_score' ? 'min-w-[1280px]' : 'min-w-[920px]'
  const rows = useMemo(
    () => data.rows.slice().sort((a, b) => compareStudentId(a.student_id, b.student_id)),
    [data.rows],
  )
  return (
    <div className="overflow-x-auto rounded-sm border border-slate-200 bg-white">
      <table className={cn('w-full border-collapse text-center text-xs text-slate-900', minWidth)}>
        <thead className="bg-slate-50 text-xs font-semibold text-slate-700">
          <tr>
            <th className="w-24 border-b border-slate-200 px-3 py-2 text-left">学生姓名</th>
            <th className="w-28 border-b border-slate-200 px-3 py-2 text-left">学号</th>
            {data.bins.map((bin) => (
              <th
                key={bin.key}
                className={cn(
                  'border-b border-slate-200 px-3 py-2',
                  bin.separator_after && 'border-r-2 border-r-slate-900',
                )}
              >
                {bin.label}
              </th>
            ))}
            <th className="w-20 border-b border-slate-200 px-3 py-2">有效次数</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.student_id)} className={index % 2 ? 'bg-slate-50/80' : 'bg-white'}>
              <td className="border-b border-slate-100 px-3 py-2 text-left font-medium">
                <Link href={`/student/${row.student_id}`} className="text-brand-600 hover:text-brand-700">
                  {String(row.name || row.student_id)}
                </Link>
              </td>
              <td className="border-b border-slate-100 px-3 py-2 text-left font-mono text-slate-500">
                {String(row.student_id)}
              </td>
              {data.bins.map((bin) => (
                <td
                  key={bin.key}
                  className={cn(
                    'border-b border-slate-100 px-3 py-2 tabular-nums',
                    bin.separator_after && 'border-r-2 border-r-slate-900',
                  )}
                >
                  {Number(row[bin.key] || 0)}
                </td>
              ))}
              <td className="border-b border-slate-100 px-3 py-2 font-medium tabular-nums">
                {Number(row.total_count || 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RankRangeTable({ data }: { data: RankRangeResponse }) {
  return (
    <div className="overflow-x-auto rounded-sm border border-slate-200 bg-white">
      <table className="w-full min-w-[720px] border-collapse text-left text-sm text-slate-900">
        <thead className="bg-slate-50 text-xs font-semibold text-slate-700">
          <tr>
            <th className="border-b border-slate-200 px-3 py-2">学号</th>
            <th className="border-b border-slate-200 px-3 py-2">学生姓名</th>
            <th className="border-b border-slate-200 px-3 py-2 text-right">分数</th>
            <th className="border-b border-slate-200 px-3 py-2 text-right">班级排名</th>
            <th className="border-b border-slate-200 px-3 py-2 text-right">年级排名</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.student_id}>
              <td className="border-b border-slate-100 px-3 py-2 font-mono text-xs text-slate-500">
                {row.student_id}
              </td>
              <td className="border-b border-slate-100 px-3 py-2 font-medium">
                <Link href={`/student/${row.student_id}`} className="text-brand-600 hover:text-brand-700">
                  {row.name}
                </Link>
              </td>
              <td className="border-b border-slate-100 px-3 py-2 text-right tabular-nums">
                {formatTableNumber(row.score)}
              </td>
              <td className="border-b border-slate-100 px-3 py-2 text-right tabular-nums">
                {formatInt(row.class_rank)}
              </td>
              <td className="border-b border-slate-100 px-3 py-2 text-right font-medium tabular-nums">
                {formatInt(row.year_rank)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 按教学班分组的高/临界/薄弱人数表；我的教学班（mine）高亮并置顶。 */
function RankBandByClassTable({
  data,
  labels,
}: {
  data: RankBandEntry[]
  labels: { high_score: string; critical: string; weak: string }
}) {
  return (
    <div className="overflow-x-auto rounded-sm border border-slate-200 bg-white">
      <table className="w-full min-w-[360px] border-collapse text-center text-xs text-slate-900">
        <thead className="bg-slate-50 text-xs font-semibold text-slate-700">
          <tr>
            <th className="border-b border-slate-200 px-3 py-2 text-left">班级</th>
            <th className="border-b border-slate-200 px-3 py-2">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-blue-500" />
                {labels.high_score}
              </span>
            </th>
            <th className="border-b border-slate-200 px-3 py-2">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-500" />
                {labels.critical}
              </span>
            </th>
            <th className="border-b border-slate-200 px-3 py-2">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-red-500" />
                {labels.weak}
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => {
            const mine = row.mine
            return (
              <tr
                key={`${row.total_type}-${bandEntryLabel(row)}`}
                className={mine ? 'bg-brand-50' : 'bg-white'}
              >
                <td className="border-b border-slate-100 px-3 py-2 text-left font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    {mine ? (
                      <Badge className="bg-brand-500 text-white hover:bg-brand-500">
                        我的班
                      </Badge>
                    ) : null}
                    <span className={mine ? 'text-brand-700' : 'text-slate-700'}>
                      {bandEntryLabel(row)}
                    </span>
                  </span>
                </td>
                <td className={cn('border-b border-slate-100 px-3 py-2 tabular-nums', mine && 'font-semibold text-brand-700')}>
                  {formatInt(row.high_score)}
                </td>
                <td className={cn('border-b border-slate-100 px-3 py-2 tabular-nums', mine && 'font-semibold text-brand-700')}>
                  {formatInt(row.critical)}
                </td>
                <td className={cn('border-b border-slate-100 px-3 py-2 tabular-nums', mine && 'font-semibold text-brand-700')}>
                  {formatInt(row.weak)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function StudentScoresTable({
  grade,
  rows,
  subjectRange,
  studentSortKey,
  studentSortDir,
  onSort,
  badgeOf,
}: {
  grade: number
  rows: StudentRow[]
  subjectRange: Record<string, { min: number; max: number }>
  studentSortKey: string | null
  studentSortDir: SortDirection
  onSort: (key: string) => void
  badgeOf: (row: StudentRow) => string | null
}) {
  if (grade === 1) {
    return (
      <div className="max-h-[calc(100vh-18rem)] overflow-auto rounded-sm border border-slate-300 bg-white">
        <table className="w-full min-w-[2100px] border-collapse text-center text-xs text-slate-900">
          <thead className="bg-white text-sm font-semibold text-slate-950">
            <tr>
              <ScoreTitleHead colSpan={35} className="sticky top-0 z-40 h-8">
                学生成绩（在籍）
              </ScoreTitleHead>
            </tr>
            <tr>
              <ScoreHead rowSpan={2} className="sticky left-0 top-8 z-50 w-[84px] min-w-[84px] bg-white">
                <SortButton label="学号" sortKey="student_id" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
              </ScoreHead>
              <ScoreHead rowSpan={2} className="sticky left-[84px] top-8 z-50 w-12 min-w-12 bg-white">
                <SortButton label="班级" sortKey="class_num" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
              </ScoreHead>
              <ScoreHead rowSpan={2} className="sticky left-[132px] top-8 z-50 w-16 min-w-16 bg-white">
                教学班
              </ScoreHead>
              <ScoreHead rowSpan={2} className="sticky left-[196px] top-8 z-50 w-12 min-w-12 bg-white">
                <SortButton label="学籍" sortKey="xueji" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
              </ScoreHead>
              <ScoreHead rowSpan={2} className="sticky left-[244px] top-8 z-50 w-20 min-w-20 bg-white shadow-[inset_-2px_0_0_#475569]">
                <SortButton label="姓名" sortKey="name" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
              </ScoreHead>
              {ALL_AVERAGE_SUBJECTS.map((subject) => (
                <ScoreHead key={subject} colSpan={2} className="sticky top-8 z-30 h-10 bg-white">
                  {subject}
                </ScoreHead>
              ))}
              {(['主三门', '五门', '九门'] as const).map((totalType) => (
                <ScoreHead key={totalType} colSpan={4} className="sticky top-8 z-30 h-10 bg-white">
                  {totalType}
                </ScoreHead>
              ))}
            </tr>
            <tr>
              {ALL_AVERAGE_SUBJECTS.map((subject) => (
                <Fragment key={subject}>
                  <ScoreHead className="sticky top-[72px] z-30 h-9 w-16 bg-white">
                    <SortButton label="分数" sortKey={`subj:${subject}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                  </ScoreHead>
                  <ScoreHead className="sticky top-[72px] z-30 h-9 w-20 bg-white">
                    <SortButton label="年级百分位" sortKey={`pct:${subject}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                  </ScoreHead>
                </Fragment>
              ))}
              {(['主三门', '五门', '九门'] as const).map((totalType) => (
                <Fragment key={totalType}>
                  <ScoreHead className="sticky top-[72px] z-30 h-9 w-16 bg-white">
                    <SortButton label="总分" sortKey={`total:${totalType}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                  </ScoreHead>
                  <ScoreHead className="sticky top-[72px] z-30 h-9 w-20 bg-white">
                    <SortButton label="年级百分位" sortKey={`totalPct:${totalType}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                  </ScoreHead>
                  <ScoreHead className="sticky top-[72px] z-30 h-9 w-16 bg-white">
                    <SortButton label="学籍排名" sortKey={`xuejiRank:${totalType}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                  </ScoreHead>
                  <ScoreHead className="sticky top-[72px] z-30 h-9 w-16 bg-white">
                    <SortButton label="年级排名" sortKey={`gradeRank:${totalType}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                  </ScoreHead>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((student) => (
              <tr key={student.student_id} className="bg-white">
                <ScoreCell className="sticky left-0 z-20 w-[84px] min-w-[84px] bg-white font-mono text-xs text-slate-600">
                  {student.student_id}
                </ScoreCell>
                <ScoreCell className="sticky left-[84px] z-20 w-12 min-w-12 bg-white text-slate-600">
                  {student.class_num != null ? student.class_num : '—'}
                </ScoreCell>
                <ScoreCell className="sticky left-[132px] z-20 w-16 min-w-16 bg-white text-slate-600">
                  <ClassBadgeText text={badgeOf(student)} />
                </ScoreCell>
                <ScoreCell className="sticky left-[196px] z-20 w-12 min-w-12 bg-white text-slate-600">
                  {student.xueji ?? '—'}
                </ScoreCell>
                <ScoreCell className="sticky left-[244px] z-20 w-20 min-w-20 bg-white text-left shadow-[inset_-2px_0_0_#cbd5e1]">
                  <Link href={`/student/${student.student_id}`} className="font-medium text-slate-900 hover:text-brand-600">
                    {student.name}
                  </Link>
                </ScoreCell>
                {ALL_AVERAGE_SUBJECTS.map((subject) => (
                  <Fragment key={subject}>
                    <StudentScoreCell value={getStudentSubjectScore(student, subject)} range={subjectRange[subject]} />
                    <StudentPercentileCell value={getStudentSubjectPercentile(student, subject)} />
                  </Fragment>
                ))}
                {(['主三门', '五门', '九门'] as const).map((totalType) => (
                  <Fragment key={totalType}>
                    <StudentScoreCell value={getStudentTotalScore(student, totalType)} className="font-semibold" />
                    <StudentPercentileCell value={getStudentTotalPercentile(student, totalType)} />
                    <StudentScoreCell value={getStudentTotalXuejiRank(student, totalType)} />
                    <StudentScoreCell value={getStudentTotalGradeRank(student, totalType)} />
                  </Fragment>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="max-h-[calc(100vh-18rem)] overflow-auto rounded-sm border border-slate-300 bg-white">
      <table className="w-full min-w-[1660px] border-collapse text-center text-xs text-slate-900">
        <thead className="bg-[#dbe4f2] text-sm font-semibold text-slate-950">
          <tr>
            <ScoreHead rowSpan={2} className="sticky left-0 top-0 z-50 w-[84px] min-w-[84px] bg-[#dbe4f2]">
              <SortButton label="学号" sortKey="student_id" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
            </ScoreHead>
            <ScoreHead rowSpan={2} className="sticky left-[84px] top-0 z-50 w-20 min-w-20 bg-[#dbe4f2]">
              <SortButton label="姓名" sortKey="name" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
            </ScoreHead>
            <ScoreHead rowSpan={2} className="sticky left-[164px] top-0 z-50 w-16 min-w-16 bg-[#dbe4f2]">
              教学班
            </ScoreHead>
            <ScoreHead rowSpan={2} className="sticky left-[228px] top-0 z-50 w-14 min-w-14 bg-[#dbe4f2] shadow-[inset_-2px_0_0_#475569]">
              <SortButton label="班级" sortKey="class_num" active={studentSortKey} dir={studentSortDir} onSort={onSort} />
            </ScoreHead>
            {BASE_AVERAGE_SUBJECTS.map((subject) => (
              <ScoreHead key={subject} colSpan={2} className="sticky top-0 z-30 h-10 bg-[#dbe4f2]">
                {subject}
              </ScoreHead>
            ))}
            {ELECTIVE_AVERAGE_SUBJECTS.map((subject) => (
              <ScoreHead key={subject} colSpan={2} className="sticky top-0 z-30 h-10 bg-[#dbe4f2]">
                {subject}
              </ScoreHead>
            ))}
            <ScoreHead colSpan={1} className="sticky top-0 z-30 h-10 bg-[#dbe4f2]">加三均分</ScoreHead>
            <ScoreHead colSpan={2} className="sticky top-0 z-30 h-10 bg-[#dbe4f2]">主三门总分</ScoreHead>
            <ScoreHead colSpan={2} className="sticky top-0 z-30 h-10 bg-[#dbe4f2]">3+3总分</ScoreHead>
          </tr>
          <tr>
            {BASE_AVERAGE_SUBJECTS.map((subject) => (
              <Fragment key={subject}>
                <ScoreHead className="sticky top-10 z-30 h-9 w-16 bg-[#dbe4f2]">
                  <SortButton label="分数" sortKey={`subj:${subject}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                </ScoreHead>
                <ScoreHead className="sticky top-10 z-30 h-9 w-20 bg-[#dbe4f2]">
                  <SortButton label="年级百分位" sortKey={`pct:${subject}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                </ScoreHead>
              </Fragment>
            ))}
            {ELECTIVE_AVERAGE_SUBJECTS.map((subject) => (
              <Fragment key={subject}>
                <ScoreHead className="sticky top-10 z-30 h-9 w-16 bg-[#dbe4f2]">
                  <SortButton label="原始分" sortKey={`subj:${subject}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                </ScoreHead>
                <ScoreHead className="sticky top-10 z-30 h-9 w-16 bg-[#dbe4f2]">
                  <SortButton label="等级分" sortKey={`subjGrade:${subject}`} active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
                </ScoreHead>
              </Fragment>
            ))}
            <ScoreHead className="sticky top-10 z-30 h-9 w-20 bg-[#dbe4f2]">
              <SortButton label="分数" sortKey="total:+3" active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
            </ScoreHead>
            <ScoreHead className="sticky top-10 z-30 h-9 w-20 bg-[#dbe4f2]">
              <SortButton label="分数" sortKey="total:主三门" active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
            </ScoreHead>
            <ScoreHead className="sticky top-10 z-30 h-9 w-16 bg-[#dbe4f2]">
              <SortButton label="排名" sortKey="rank:主三门" active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
            </ScoreHead>
            <ScoreHead className="sticky top-10 z-30 h-9 w-20 bg-[#dbe4f2]">
              <SortButton label="分数" sortKey="total:3+3" active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
            </ScoreHead>
            <ScoreHead className="sticky top-10 z-30 h-9 w-16 bg-[#dbe4f2]">
              <SortButton label="排名" sortKey="rank:3+3" active={studentSortKey} dir={studentSortDir} onSort={onSort} align="center" />
            </ScoreHead>
          </tr>
        </thead>
        <tbody>
          {rows.map((student) => (
            <tr key={student.student_id} className="bg-white">
              <ScoreCell className="sticky left-0 z-20 w-[84px] min-w-[84px] bg-white font-mono text-xs text-slate-600">
                {student.student_id}
              </ScoreCell>
              <ScoreCell className="sticky left-[84px] z-20 w-20 min-w-20 bg-white text-left">
                <Link href={`/student/${student.student_id}`} className="font-medium text-slate-900 hover:text-brand-600">
                  {student.name}
                </Link>
              </ScoreCell>
              <ScoreCell className="sticky left-[164px] z-20 w-16 min-w-16 bg-white text-slate-600">
                <ClassBadgeText text={badgeOf(student)} />
              </ScoreCell>
              <ScoreCell className="sticky left-[228px] z-20 w-14 min-w-14 bg-white text-slate-600 shadow-[inset_-2px_0_0_#cbd5e1]">
                {student.class_num != null ? `${student.class_num}班` : '—'}
              </ScoreCell>
              {BASE_AVERAGE_SUBJECTS.map((subject) => (
                <Fragment key={subject}>
                  <StudentScoreCell value={getStudentSubjectScore(student, subject)} range={subjectRange[subject]} />
                  <StudentPercentileCell value={getStudentSubjectPercentile(student, subject)} />
                </Fragment>
              ))}
              {ELECTIVE_AVERAGE_SUBJECTS.map((subject) => (
                <Fragment key={subject}>
                  <StudentScoreCell value={getStudentSubjectScore(student, subject)} range={subjectRange[subject]} />
                  <StudentScoreCell value={getStudentSubjectScore(student, subject, 'grade')} />
                </Fragment>
              ))}
              <StudentScoreCell value={getStudentTotalScore(student, '+3')} className="font-semibold" />
              <StudentScoreCell value={getStudentTotalScore(student, '主三门')} className="font-semibold" />
              <StudentScoreCell value={getStudentTotalRank(student, '主三门')} />
              <StudentScoreCell value={getStudentTotalScore(student, '3+3')} className="font-semibold" />
              <StudentScoreCell value={getStudentTotalRank(student, '3+3')} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// 手机端：把超宽的学生成绩矩阵换成「一个学生一张卡」的纵向阅读视图。
// 仅 <md 显示（桌面用上面的宽表）。数据取数复用与宽表相同的 getter，口径一致。
function StudentScoreMobileCards({
  grade,
  rows,
  badgeOf,
}: {
  grade: number
  rows: StudentRow[]
  badgeOf: (row: StudentRow) => string | null
}) {
  const isGradeOne = grade === 1
  const totalTypes = isGradeOne
    ? (['主三门', '五门', '九门'] as const)
    : (['主三门', '3+3'] as const)

  return (
    <div className="space-y-3 md:hidden">
      {rows.map((student) => (
        <div
          key={student.student_id}
          className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
        >
          {/* 头部：姓名 + 教学班徽章 / 班级 / 学籍 / 学号 */}
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-2">
            <Link
              href={`/student/${student.student_id}`}
              className="font-medium text-slate-900 hover:text-brand-600"
            >
              {student.name}
            </Link>
            <div className="flex flex-wrap items-center justify-end gap-1.5 text-xs text-slate-500">
              {(() => {
                const text = badgeOf(student)
                return text ? (
                  <Badge variant="secondary" className="font-normal">
                    {text}
                  </Badge>
                ) : null
              })()}
              {student.class_num != null && (
                <Badge variant="secondary" className="font-normal">
                  {student.class_num}班
                </Badge>
              )}
              {isGradeOne && student.xueji != null && <span>学籍{student.xueji}</span>}
              <span className="font-mono">{student.student_id}</span>
            </div>
          </div>

          {/* 总分块 */}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {!isGradeOne &&
              (() => {
                const plus3 = getStudentTotalScore(student, '+3')
                return plus3 == null ? null : (
                  <div className="rounded bg-slate-50 px-2 py-1 text-xs">
                    <span className="text-slate-500">加三均分</span>
                    <span className="ml-1 font-semibold tabular-nums text-slate-900">
                      {formatInt(plus3)}
                    </span>
                  </div>
                )
              })()}
            {totalTypes.map((tt) => {
              const score = getStudentTotalScore(student, tt)
              const rank = isGradeOne
                ? getStudentTotalXuejiRank(student, tt)
                : getStudentTotalRank(student, tt)
              return (
                <div key={tt} className="rounded bg-slate-50 px-2 py-1 text-xs">
                  <span className="text-slate-500">{tt}</span>
                  <span className="ml-1 font-semibold tabular-nums text-slate-900">
                    {score == null ? '—' : formatInt(score)}
                  </span>
                  {rank != null && (
                    <span className="ml-1 text-slate-400">
                      {isGradeOne ? '学籍' : ''}名次{formatInt(rank)}
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {/* 各科：分数 +（高一/基础科=年级百分位；选考科=等级分） */}
          <div className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2">
            {ALL_AVERAGE_SUBJECTS.map((subject) => {
              const isElective =
                !isGradeOne &&
                (ELECTIVE_AVERAGE_SUBJECTS as readonly string[]).includes(subject)
              const score = getStudentSubjectScore(student, subject)
              const secondary = isElective
                ? getStudentSubjectScore(student, subject, 'grade')
                : getStudentSubjectPercentile(student, subject)
              return (
                <div key={subject} className="flex flex-col">
                  <span className="text-[11px] text-slate-400">{subject}</span>
                  <span className="font-medium tabular-nums text-slate-800">
                    {score == null ? '—' : formatInt(score)}
                  </span>
                  {secondary != null && (
                    <span className="text-[10px] tabular-nums text-slate-400">
                      {isElective ? `等级${formatInt(secondary)}` : `位${formatPercentile(secondary)}`}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/** 桌面宽表 sticky 列里的教学班徽章文本（窄列，直接缩写文本）。 */
function ClassBadgeText({ text }: { text: string | null }) {
  if (!text) return <span className="text-slate-300">—</span>
  return <span className="text-slate-600">{text}</span>
}

function StudentScoreRow({
  student,
  subjectRange,
}: {
  student: StudentRow
  subjectRange: Record<string, { min: number; max: number }>
}) {
  return (
    <TableRow>
      <TableCell className="font-mono text-xs text-slate-600">{student.student_id}</TableCell>
      <TableCell>
        <Link href={`/student/${student.student_id}`} className="font-medium text-slate-900 hover:text-brand-600">
          {student.name}
        </Link>
      </TableCell>
      <TableCell className="text-sm text-slate-600">
        {student.class_num != null ? `${student.class_num}班` : '—'}
      </TableCell>
      {SUBJECT_KEYS.map(({ key }) => (
        <StudentScoreCell key={key} value={getStudentSubjectScore(student, key)} range={subjectRange[key]} asTableCell />
      ))}
      <TableCell className="text-right text-sm font-medium tabular-nums">
        {student.total_score == null ? '—' : formatInt(student.total_score)}
      </TableCell>
      <TableCell className="text-right text-sm tabular-nums text-slate-600">
        {student.grade_rank == null ? '—' : formatInt(student.grade_rank)}
      </TableCell>
    </TableRow>
  )
}

function StudentScoreCell({
  value,
  range,
  className,
  asTableCell = false,
}: {
  value: number | null
  range?: { min: number; max: number }
  className?: string
  asTableCell?: boolean
}) {
  const cls = range
    ? heatmapClass(value, range.min, range.max)
    : value == null
    ? 'bg-slate-50 text-slate-400'
    : 'bg-white text-slate-700'
  const content = value == null ? '—' : formatInt(value)
  if (asTableCell) {
    return (
      <TableCell className={cn('text-center text-sm tabular-nums', cls, className)}>
        {content}
      </TableCell>
    )
  }
  return <ScoreCell className={cn('tabular-nums', cls, className)}>{content}</ScoreCell>
}

function StudentPercentileCell({
  value,
  className,
}: {
  value: number | null
  className?: string
}) {
  return (
    <ScoreCell
      className={cn(
        'tabular-nums',
        value == null ? 'bg-slate-50 text-slate-400' : 'bg-white text-slate-700',
        className,
      )}
    >
      {formatPercentile(value)}
    </ScoreCell>
  )
}

function ScoreTitleHead({
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'border-y-2 border-black bg-white px-1 py-1.5 text-center text-sm font-semibold text-slate-950',
        className,
      )}
      {...props}
    />
  )
}

function ScoreHead({
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'border border-slate-600 px-1 py-1 align-middle whitespace-nowrap',
        className,
      )}
      {...props}
    />
  )
}

function ScoreCell({
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        'border border-slate-300 px-1.5 py-1 align-middle whitespace-nowrap',
        className,
      )}
      {...props}
    />
  )
}

function ClassAverageDingTable({
  rows,
  grade,
}: {
  rows: ClassAverage[]
  grade: number
}) {
  const groups = groupClassAverages(rows)
  const metrics = getClassAverageMetrics(grade)
  const rankMap = buildClassAverageRanks(rows, metrics)
  const summaryKinds: AverageSummaryKind[] = ['平均', '最高', '最低']
  const isGradeOne = grade === 1

  return (
    <div className="overflow-x-auto rounded-sm border border-slate-400 bg-white">
      <table
        className={cn(
          'w-full table-fixed border-collapse text-center text-[10px] leading-tight text-slate-900',
          isGradeOne ? 'min-w-[980px]' : 'min-w-[1040px]',
        )}
      >
        <thead className="bg-[#dbe4f2] text-[11px] font-semibold text-slate-950">
          <tr>
            <AverageHead rowSpan={2} className="w-20">
              班级类型
            </AverageHead>
            <AverageHead rowSpan={2} className="w-14">
              班级
            </AverageHead>
            <AverageHead rowSpan={2} className="w-16">
              班主任
            </AverageHead>
            {isGradeOne ? (
              <>
                {ALL_AVERAGE_SUBJECTS.map((subject) => (
                  <AverageHead key={subject} rowSpan={2} className="w-16">
                    {subject}
                  </AverageHead>
                ))}
                <AverageHead colSpan={2}>主三门总分</AverageHead>
                <AverageHead colSpan={2}>五门总分</AverageHead>
                <AverageHead colSpan={2}>九门总分</AverageHead>
              </>
            ) : (
              <>
                {BASE_AVERAGE_SUBJECTS.map((subject) => (
                  <AverageHead key={subject} rowSpan={2} className="w-16">
                    {subject}
                  </AverageHead>
                ))}
                {ELECTIVE_AVERAGE_SUBJECTS.map((subject) => (
                  <AverageHead key={subject} colSpan={2}>
                    {subject}
                  </AverageHead>
                ))}
                <AverageHead colSpan={1}>加三均分</AverageHead>
                <AverageHead colSpan={2}>主三门总分</AverageHead>
                <AverageHead colSpan={2}>3+3总分</AverageHead>
              </>
            )}
          </tr>
          <tr>
            {isGradeOne ? null : (
              <>
                {ELECTIVE_AVERAGE_SUBJECTS.map((subject) => (
                  <Fragment key={subject}>
                    <AverageHead className="w-14">原始分</AverageHead>
                    <AverageHead className="w-14">等级分</AverageHead>
                  </Fragment>
                ))}
                <AverageHead className="w-16">分数</AverageHead>
              </>
            )}
            {(isGradeOne ? ['主三门', '五门', '九门'] : ['主三门', '3+3']).map(
              (totalKey) => (
                <Fragment key={totalKey}>
                  <AverageHead className="w-16">分数</AverageHead>
                  <AverageHead className="w-12">排名</AverageHead>
                </Fragment>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <Fragment key={group.type}>
              {group.rows.map((row, index) => (
                <tr key={`${group.type}-${row.class_num}`} className="bg-white">
                  {index === 0 ? (
                    <AverageCell
                      rowSpan={group.rows.length}
                      className="bg-white font-semibold"
                    >
                      {group.type}
                    </AverageCell>
                  ) : null}
                  <AverageCell className="font-semibold text-blue-600">
                    {row.class_label || String(row.class_num).padStart(2, '0')}
                  </AverageCell>
                  <AverageCell className="font-semibold">
                    {row.teacher_name || ''}
                  </AverageCell>
                  {metrics.map((metric) => (
                    <AverageCell
                      key={metricId(metric)}
                      className={cn(
                        'tabular-nums',
                        metric.source === 'rank' && 'font-semibold',
                      )}
                    >
                      {metric.source === 'rank'
                        ? getRankValue(row, group.type, metric, rankMap) ?? ''
                        : formatTableNumber(
                            getClassAverageMetricValue(row, metric),
                          )}
                    </AverageCell>
                  ))}
                </tr>
              ))}
              {summaryKinds.map((kind, index) => (
                <tr key={`${group.type}-summary-${kind}`}>
                  {index === 0 ? (
                    <AverageCell
                      rowSpan={summaryKinds.length}
                      className="bg-white font-semibold"
                    >
                      {group.type}汇总
                    </AverageCell>
                  ) : null}
                  <AverageCell className="font-semibold">{kind}</AverageCell>
                  <AverageCell />
                  {metrics.map((metric) => (
                    <AverageCell
                      key={`${kind}-${metricId(metric)}`}
                      className={cn(
                        'tabular-nums font-semibold',
                        kind === '最高' && metric.source !== 'rank'
                          ? 'bg-[#ff8f66] text-slate-950'
                          : '',
                        kind === '最低' && metric.source !== 'rank'
                          ? 'bg-[#8d8d8d] text-slate-950'
                          : '',
                      )}
                    >
                      {formatTableNumber(
                        getClassAverageSummaryValue(group.rows, metric, kind),
                      )}
                    </AverageCell>
                  ))}
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AverageHead({
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'border border-slate-600 px-1 py-1.5 align-middle whitespace-nowrap',
        className,
      )}
      {...props}
    />
  )
}

function AverageCell({
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        'border border-slate-300 px-1 py-1.5 align-middle whitespace-nowrap',
        className,
      )}
      {...props}
    />
  )
}

// ===== helpers =====

function getSortValue(
  row: StudentRow,
  key: string,
): string | number | null {
  if (key.startsWith('subj:')) {
    const subject = key.slice(5)
    return getStudentSubjectScore(row, subject)
  }
  if (key.startsWith('subjGrade:')) {
    const subject = key.slice(10)
    return getStudentSubjectScore(row, subject, 'grade')
  }
  if (key.startsWith('pct:')) {
    const subject = key.slice(4)
    return getStudentSubjectPercentile(row, subject)
  }
  if (key.startsWith('total:')) {
    const totalType = key.slice(6)
    return getStudentTotalScore(row, totalType)
  }
  if (key.startsWith('totalPct:')) {
    const totalType = key.slice(9)
    return getStudentTotalPercentile(row, totalType)
  }
  if (key.startsWith('rank:')) {
    const totalType = key.slice(5)
    return getStudentTotalRank(row, totalType)
  }
  if (key.startsWith('xuejiRank:')) {
    const totalType = key.slice(10)
    return getStudentTotalXuejiRank(row, totalType)
  }
  if (key.startsWith('gradeRank:')) {
    const totalType = key.slice(10)
    return getStudentTotalGradeRank(row, totalType)
  }
  switch (key) {
    case 'student_id':
      return row.student_id || null
    case 'name':
      return row.name || null
    case 'class_num':
      return row.class_num ?? null
    case 'xueji':
      return row.xueji ?? null
    case 'total_score':
      return row.total_score ?? null
    case 'grade_rank':
      return row.grade_rank ?? null
    default:
      return null
  }
}

interface KpiCardProps {
  icon: React.ReactNode
  title: string
  value: string
  hint?: string
}

function KpiCard({ icon, title, value, hint }: KpiCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-slate-500">
          {title}
        </CardTitle>
        <span className="text-slate-400">{icon}</span>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold text-slate-900 tabular-nums">
          {value}
        </div>
        {hint ? (
          <p className="mt-1 text-xs text-slate-500">{hint}</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

interface EmptyStateProps {
  icon: React.ReactNode
  title: string
  desc?: string
}

function EmptyState({ icon, title, desc }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100">
        {icon}
      </div>
      <div className="text-base font-medium text-slate-900">{title}</div>
      {desc ? <div className="text-sm text-slate-500">{desc}</div> : null}
    </div>
  )
}

interface SortableHeadProps {
  label: string
  sortKey: string
  active: string | null
  dir: SortDirection
  onSort: (key: string) => void
  className?: string
  align?: 'left' | 'center' | 'right'
}

function SortButton({
  label,
  sortKey,
  active,
  dir,
  onSort,
  align = 'left',
}: SortableHeadProps) {
  const isActive = active === sortKey && dir
  const Icon =
    isActive && dir === 'asc'
      ? ArrowUp
      : isActive && dir === 'desc'
      ? ArrowDown
      : ArrowUpDown
  const justify =
    align === 'center'
      ? 'justify-center'
      : align === 'right'
      ? 'justify-end'
      : 'justify-start'

  return (
    <button
      type="button"
      onClick={() => onSort(sortKey)}
      className={cn(
        'flex w-full items-center gap-1 text-xs font-semibold text-slate-900 hover:text-brand-700',
        justify,
      )}
    >
      <span>{label}</span>
      <Icon
        className={cn(
          'h-3 w-3',
          isActive ? 'text-slate-900' : 'text-slate-400',
        )}
      />
    </button>
  )
}

function SortableHead({
  label,
  sortKey,
  active,
  dir,
  onSort,
  className,
  align = 'left',
}: SortableHeadProps) {
  const isActive = active === sortKey && dir
  const Icon =
    isActive && dir === 'asc'
      ? ArrowUp
      : isActive && dir === 'desc'
      ? ArrowDown
      : ArrowUpDown
  const justify =
    align === 'center'
      ? 'justify-center'
      : align === 'right'
      ? 'justify-end'
      : 'justify-start'
  return (
    <TableHead className={cn('cursor-pointer select-none', className)}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          'flex w-full items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-900',
          justify,
        )}
      >
        <span>{label}</span>
        <Icon
          className={cn(
            'h-3 w-3',
            isActive ? 'text-slate-900' : 'text-slate-300',
          )}
        />
      </button>
    </TableHead>
  )
}
