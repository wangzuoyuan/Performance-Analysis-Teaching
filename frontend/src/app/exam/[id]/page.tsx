'use client'

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import {
  Bar,
  BarChart,
  CartesianGrid,
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
  BookOpen,
  ChevronLeft,
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
import { ClassScopePicker } from '@/components/ClassScopePicker'
import { useClassScope, formatClassChip } from '@/lib/class-scope'
import { formatGradeLabel } from '@/lib/labels'

// ── 单学科化后的类型（与 backend get_exam 响应对齐） ──

interface ExamDetail {
  id: number
  name: string
  grade: number
  semester?: string | null
  exam_date: string
  exam_type?: string | null
}

interface ClassAverage {
  class_num: number | null
  class_label?: string | null
  class_type?: string | null
  teacher_name?: string | null
  subject_averages?: Record<string, number | null> | null
}

interface ExamStats {
  total_students?: number | null
  avg?: number | null
  max?: number | null
  min?: number | null
  rank_min?: number | null
  rank_max?: number | null
  score_basis?: string | null
}

interface StudentRow {
  student_id: string
  name: string
  class_num?: number | null
  class_label?: string | null
  xueji?: number | null
  raw_score?: number | null
  grade_score?: number | null
  grade_percentile?: number | null
  rank?: number | null
}

interface RankBandEntry {
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

interface RankDistributionEntry {
  band: string
  [key: string]: string | number
}

interface ExamApiResponse {
  exam: ExamDetail
  subject?: string | null
  teaching_class_id?: number | null
  class_averages?: ClassAverage[]
  stats?: ExamStats
  students?: StudentRow[]
  rank_bands?: RankBandEntry[]
  band_config?: BandConfig
  rank_distribution?: RankDistributionEntry[]
}

const DEFAULT_BAND_CONFIG: BandConfig = {
  high_score_max: 80,
  critical_min: 400,
  critical_max: 500,
  weak_min: 501,
}

function formatNumber(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toFixed(digits)
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

const RANK_DISTRIBUTION_COLOR = '#4098ff'

export default function ExamDetailPage() {
  const params = useParams<{ id: string }>()
  const examId = params?.id
  // 单学科化：教学班范围由 ClassScopeProvider 统一管理；current 变化即重新拉取。
  const { current, currentClass } = useClassScope()

  const [exam, setExam] = useState<ExamDetail | null>(null)
  const [subject, setSubject] = useState<string | null>(null)
  const [classAverages, setClassAverages] = useState<ClassAverage[]>([])
  const [stats, setStats] = useState<ExamStats>({})
  const [students, setStudents] = useState<StudentRow[]>([])
  const [rankBands, setRankBands] = useState<RankBandEntry[]>([])
  const [rankDistribution, setRankDistribution] = useState<RankDistributionEntry[]>([])
  const [bandConfig, setBandConfig] = useState<BandConfig>(DEFAULT_BAND_CONFIG)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [studentQuery, setStudentQuery] = useState('')
  const [studentSortKey, setStudentSortKey] = useState<string | null>(null)
  const [studentSortDir, setStudentSortDir] = useState<'asc' | 'desc' | null>(null)
  const [activeTab, setActiveTab] = useState('scores')

  useEffect(() => {
    if (!examId) return
    let cancelled = false
    setLoading(true)
    setError(null)

    const tcParam = current !== 'all' ? `?teaching_class_id=${current}` : ''
    fetch(`/api/exams/${examId}${tcParam}`)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => null)
          throw new Error(body?.detail || `HTTP ${r.status}`)
        }
        return (await r.json()) as ExamApiResponse
      })
      .then((data) => {
        if (cancelled) return
        setExam(data.exam)
        setSubject(data.subject ?? null)
        setClassAverages(data.class_averages || [])
        setStats(data.stats || {})
        setStudents(data.students || [])
        setRankBands(data.rank_bands || [])
        setRankDistribution(data.rank_distribution || [])
        setBandConfig(data.band_config || DEFAULT_BAND_CONFIG)
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
    // current 变化（切换教学班）即重新拉取
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examId, current])

  function studentBadge(row: StudentRow): string | null {
    // 后端 get_exam 已在每个学生行直接返回 class_label（教学范围标签），
    // 不再需要额外调用学生汇总接口建立映射。
    if (row.class_label) return formatClassChip(row.class_label)
    if (current !== 'all' && currentClass) return formatClassChip(currentClass.label)
    if (row.class_num != null) return `${row.class_num}班`
    return null
  }

  const subjectLabel = subject ?? '当前学科'

  const examKpis = useMemo<Array<{ icon: ReactNode; title: string; value: string; hint: string }>>(
    () => [
      {
        icon: <BookOpen className="h-4 w-4" />,
        title: `${subjectLabel}平均`,
        value: formatNumber(stats.avg),
        hint: stats.score_basis === 'grade_score' ? '等级分口径' : '原始分口径',
      },
      {
        icon: <TrendingUp className="h-4 w-4" />,
        title: '最高分',
        value: formatNumber(stats.max),
        hint: subjectLabel,
      },
      {
        icon: <Hash className="h-4 w-4" />,
        title: '最低分',
        value: formatNumber(stats.min),
        hint: subjectLabel,
      },
      {
        icon: <Users className="h-4 w-4" />,
        title: '参考人数',
        value: formatInt(stats.total_students),
        hint: '当前教学范围',
      },
    ],
    [subjectLabel, stats],
  )

  // 单科名次分布图（只有一个当前学科列）
  const distributionData = useMemo(() => {
    if (!subject || rankDistribution.length === 0) return []
    return rankDistribution.map((b) => ({
      band: b.band,
      count: (b[subject] as number) ?? 0,
    }))
  }, [rankDistribution, subject])

  const bandLabels = {
    high_score: `高分段(1-${bandConfig.high_score_max})`,
    critical: `临界段(${bandConfig.critical_min}-${bandConfig.critical_max})`,
    weak: `薄弱段(≥${bandConfig.weak_min})`,
  }

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
        const av = sortValue(a, studentSortKey)
        const bv = sortValue(b, studentSortKey)
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

  function sortIcon(key: string) {
    if (studentSortKey !== key)
      return <ArrowUpDown className="ml-1 inline h-3 w-3 text-slate-300" />
    if (studentSortDir === 'asc') return <ArrowUp className="ml-1 inline h-3 w-3 text-brand-500" />
    if (studentSortDir === 'desc') return <ArrowDown className="ml-1 inline h-3 w-3 text-brand-500" />
    return <ArrowUpDown className="ml-1 inline h-3 w-3 text-slate-300" />
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
          <div className="text-sm text-slate-500">{error || '未找到该考试'}</div>
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
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              {exam.name}
              {subject ? (
                <span className="ml-2 text-base font-normal text-slate-500">{subject}</span>
              ) : null}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              {subject ? `${subject}单科成绩分析` : '成绩分析'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* 教学班范围选择器：切换后整页按所选教学班重新统计 */}
            <ClassScopePicker grade={exam.grade} compact />
            <Badge variant="default">{formatGradeLabel(exam.grade)}</Badge>
            <Badge variant="secondary">{exam.exam_date || '—'}</Badge>
            {exam.exam_type ? <Badge variant="outline">{exam.exam_type}</Badge> : null}
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

      {/* 单科名次分布 */}
      {distributionData.length > 0 ? (
        <Card>
          <CardContent className="px-4 py-3">
            <div className="mb-2 text-sm font-medium text-slate-700">
              {subject}名次分布
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={distributionData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="band"
                  tick={{ fontSize: 11, fill: '#64748b' }}
                  stroke="#e2e8f0"
                  interval={0}
                  angle={-20}
                  textAnchor="end"
                  height={50}
                />
                <YAxis tick={{ fontSize: 12, fill: '#64748b' }} stroke="#e2e8f0" allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#ffffff',
                    border: '1px solid #e2e8f0',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  cursor={{ fill: '#f1f5f9' }}
                />
                <Bar dataKey="count" name="人数" fill={RANK_DISTRIBUTION_COLOR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      ) : null}

      {/* Tabs: 学生成绩明细 + 分数段分布 */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="scores">学生成绩</TabsTrigger>
          <TabsTrigger value="averages">班级均分</TabsTrigger>
          <TabsTrigger value="bands">分数段分布</TabsTrigger>
        </TabsList>

        {/* Tab: 学生成绩明细（单学科列） */}
        <TabsContent value="scores">
          <Card>
            <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <CardTitle>学生{subject}成绩明细</CardTitle>
                <CardDescription>
                  仅展示当前任教学科{subject ? `（${subject}）` : ''}的原始分 / 等级分 / 百分位 / 名次。
                </CardDescription>
              </div>
              <div className="relative w-full sm:w-64">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  value={studentQuery}
                  onChange={(e) => setStudentQuery(e.target.value)}
                  placeholder="按姓名 / 学号搜索"
                  className="pl-9"
                />
              </div>
            </CardHeader>
            <CardContent>
              {students.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">暂无学生数据</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12">#</TableHead>
                        <TableHead>姓名</TableHead>
                        <TableHead className="w-28">班级</TableHead>
                        <TableHead className="cursor-pointer select-none text-right" onClick={() => toggleSort('raw')}>
                          原始分{sortIcon('raw')}
                        </TableHead>
                        <TableHead className="cursor-pointer select-none text-right" onClick={() => toggleSort('grade')}>
                          等级分{sortIcon('grade')}
                        </TableHead>
                        <TableHead className="cursor-pointer select-none text-right" onClick={() => toggleSort('percentile')}>
                          百分位{sortIcon('percentile')}
                        </TableHead>
                        <TableHead className="cursor-pointer select-none text-right" onClick={() => toggleSort('rank')}>
                          名次{sortIcon('rank')}
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleStudents.map((row, idx) => (
                        <TableRow key={row.student_id} className="hover:bg-slate-50">
                          <TableCell className="tabular-nums text-slate-400">
                            {row.rank ?? idx + 1}
                          </TableCell>
                          <TableCell>
                            <Link
                              href={`/student/${row.student_id}`}
                              className="font-medium text-slate-900 hover:text-brand-600"
                            >
                              {row.name}
                            </Link>
                            <div className="text-xs text-slate-400">{row.student_id}</div>
                          </TableCell>
                          <TableCell className="text-slate-600">
                            {studentBadge(row) ?? '—'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatNumber(row.raw_score)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatNumber(row.grade_score)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatPercentile(row.grade_percentile)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatInt(row.rank)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab: 班级均分（仅当前学科） */}
        <TabsContent value="averages">
          <Card>
            <CardHeader>
              <CardTitle>班级{subjectLabel}均分</CardTitle>
              <CardDescription>仅展示当前任教学科的班级均分对比。</CardDescription>
            </CardHeader>
            <CardContent>
              {classAverages.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">暂无班级均分数据</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>班级</TableHead>
                        <TableHead>类型</TableHead>
                        <TableHead>班主任</TableHead>
                        <TableHead className="text-right">{subjectLabel}均分</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {classAverages.map((c, i) => (
                        <TableRow
                          key={`${c.class_label ?? c.class_num ?? i}`}
                        >
                          <TableCell className="font-medium text-slate-900">
                            {c.class_label ?? (c.class_num != null ? `${c.class_num}班` : '—')}
                          </TableCell>
                          <TableCell className="text-slate-600">{c.class_type || '—'}</TableCell>
                          <TableCell className="text-slate-600">{c.teacher_name || '—'}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatNumber(c.subject_averages?.[subject ?? ''] ?? null)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab: 分数段分布（单学科名次分段，按班级） */}
        <TabsContent value="bands">
          <Card>
            <CardHeader>
              <CardTitle>{subject}名次分段</CardTitle>
              <CardDescription>
                按班级统计 {bandLabels.high_score} / {bandLabels.critical} / {bandLabels.weak} 人数。
              </CardDescription>
            </CardHeader>
            <CardContent>
              {rankBands.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">暂无分段数据</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>班级</TableHead>
                        <TableHead className="text-right text-brand-600">{bandLabels.high_score}</TableHead>
                        <TableHead className="text-right text-warning-600">{bandLabels.critical}</TableHead>
                        <TableHead className="text-right text-danger-600">{bandLabels.weak}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rankBands
                        .slice()
                        .sort((a, b) => Number(b.mine) - Number(a.mine))
                        .map((b, i) => (
                          <TableRow
                            key={b.class_label ?? i}
                            className={cn(b.mine && 'bg-brand-50/40')}
                          >
                            <TableCell className="font-medium text-slate-900">
                              {b.class_label ?? '—'}
                              {b.mine ? (
                                <Badge variant="secondary" className="ml-2">我的班</Badge>
                              ) : null}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-brand-600">
                              {b.high_score}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-warning-600">
                              {b.critical}
                            </TableCell>
                            <TableCell className="text-right tabular-nums text-danger-600">
                              {b.weak}
                            </TableCell>
                          </TableRow>
                        ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function sortValue(row: StudentRow, key: string): number | string | null {
  switch (key) {
    case 'raw':
      return row.raw_score ?? null
    case 'grade':
      return row.grade_score ?? null
    case 'percentile':
      return row.grade_percentile ?? null
    case 'rank':
      return row.rank ?? null
    default:
      return null
  }
}

function KpiCard({
  icon,
  title,
  value,
  hint,
}: {
  icon: ReactNode
  title: string
  value: string
  hint: string
}) {
  return (
    <Card>
      <CardContent className="py-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          {icon}
          {title}
        </div>
        <div className="mt-2 truncate text-2xl font-semibold text-slate-900">{value}</div>
        <div className="mt-1 truncate text-xs text-slate-400">{hint}</div>
      </CardContent>
    </Card>
  )
}
