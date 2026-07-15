'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle,
  ArrowLeft,
  CalendarDays,
  CalendarOff,
  CheckCircle2,
  ClipboardList,
  School,
  Upload,
  Users,
} from 'lucide-react'
import { LineChart, Line, ResponsiveContainer } from 'recharts'

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
import WeeklyFocusCard from '@/components/WeeklyFocusCard'
import BackupCard from '@/components/BackupCard'
import { ClassScopePicker } from '@/components/ClassScopePicker'
import {
  useClassScope,
  formatTeachingClass,
  formatClassChip,
} from '@/lib/class-scope'

interface Exam {
  id: number
  name: string
  grade: number
  exam_date: string
  exam_type?: string | null
  semester?: string | null
}

interface ExamDetailStats {
  rank_min?: number | null
  rank_max?: number | null
  avg?: number | null
  max?: number | null
  min?: number | null
  total_students?: number | null
  score_basis?: string | null
}

interface ExamDetailResponse {
  stats?: ExamDetailStats
  subject?: string | null
}

interface FocusStudent {
  student_id: string
  name: string
  class_label?: string | null
  subject_rank?: number | null
  raw_score?: number | null
  grade_score?: number | null
  issues: string[]
}

interface FocusListResponse {
  focus_list: FocusStudent[]
}

interface OverviewClass {
  id: number
  grade: number
  label: string
  teaching_class_id: number
  subject?: string | null
  kind: string
  member_count: number
  latest_exam: { id: number; name: string; exam_date: string } | null
  subject_avg: number | null
  score_basis: string
  focus_count: number
}

interface OverviewResponse {
  grade: number | null
  teaching_subject?: string | null
  classes: OverviewClass[]
  overall: { class_count: number; total_students: number }
}

type IssueTone = 'danger' | 'warning' | 'purple' | 'slate'

function classifyIssue(issues: string[]): { label: string; tone: IssueTone } {
  const text = issues.join(' ')
  if (/退步|下滑/.test(text)) return { label: issues[0] ?? '退步', tone: 'danger' }
  if (/波动/.test(text)) return { label: issues[0] ?? '波动', tone: 'warning' }
  if (/临界段/.test(text)) {
    return { label: issues.find((i) => /临界段/.test(i)) ?? '临界段', tone: 'warning' }
  }
  if (/薄弱段/.test(text)) {
    return { label: issues.find((i) => /薄弱段/.test(i)) ?? '薄弱段', tone: 'danger' }
  }
  return { label: issues[0] ?? '关注', tone: 'slate' }
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
    default:
      return 'bg-slate-200 text-slate-700 border-transparent'
  }
}

function truncate(text: string, max: number): string {
  if (!text) return ''
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function formatNumber(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(digits)
}

function formatRankRange(stats: ExamDetailStats | undefined): string {
  if (!stats || (stats.rank_min == null && stats.rank_max == null)) return '—'
  const min = stats.rank_min == null ? '—' : String(Math.round(Number(stats.rank_min)))
  const max = stats.rank_max == null ? '—' : String(Math.round(Number(stats.rank_max)))
  return `${min}-${max}`
}

function todayString(): string {
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'long',
    }).format(new Date())
  } catch {
    return new Date().toISOString().slice(0, 10)
  }
}

async function safeJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url)
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export default function Dashboard() {
  const scope = useClassScope()
  const { classes: scopeClasses, loading: scopeLoading, current, currentClass, setCurrent } = scope

  const [exams, setExams] = useState<Exam[]>([])
  const [focusList, setFocusList] = useState<FocusStudent[]>([])
  const [focusHistory, setFocusHistory] = useState<number[]>([])
  const [examStatsById, setExamStatsById] = useState<Record<number, ExamDetailStats>>({})
  const [teachingSubject, setTeachingSubject] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [focusLoading, setFocusLoading] = useState(true)
  const [showUploadPrompt, setShowUploadPrompt] = useState(false)

  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [overviewLoading, setOverviewLoading] = useState(true)

  // 全局：考试列表（与 scope 无关，只拉一次，但随 scope 携带 teaching_class_id）
  const isAll = current === 'all'
  const scopeParam = scope.scopeParam(currentClass?.grade)
  const tidParam = scopeParam.teaching_class_id
  const tidQuery = tidParam ? `?teaching_class_id=${tidParam}` : ''

  useEffect(() => {
    let cancelled = false
    async function load() {
      // 考试列表必须随当前 scope 重取并携带同一 teaching_class_id
      const examsRes = await safeJson<{ exams?: Exam[] }>(`/api/exams${tidQuery}`)
      if (cancelled) return

      const examsList = examsRes?.exams ?? []
      setExams(examsList)
      setShowUploadPrompt(examsList.length === 0)
      setLoading(false)

      // 拉每场考试的 stats（当前学科，时间线徽章用）+ 关注名单历史
      const historyTargets = examsList.slice(0, 6)
      const historyPromise = Promise.all(
        historyTargets.map((e) =>
          safeJson<FocusListResponse>(`/api/focus-list/${e.id}${tidQuery}`).then(
            (r) => r?.focus_list?.length ?? 0
          )
        )
      )
      const statsPromise = Promise.all(
        examsList.map((e) =>
          safeJson<ExamDetailResponse>(`/api/exams/${e.id}${tidQuery}`).then((r) => [
            e.id,
            r?.stats ?? {},
          ] as const)
        )
      )
      const [historyCounts, statsEntries] = await Promise.all([
        historyPromise,
        statsPromise,
      ])
      if (cancelled) return

      setFocusHistory([...historyCounts].reverse())
      setExamStatsById(Object.fromEntries(statsEntries))
    }
    load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tidQuery])

  // 关注名单 + KPI 统计：随 scope 变化
  const latestExam = exams[0] ?? null

  useEffect(() => {
    let cancelled = false
    if (!latestExam) {
      setFocusList([])
      setFocusLoading(false)
      return
    }
    setFocusLoading(true)
    safeJson<FocusListResponse>(`/api/focus-list/${latestExam.id}${tidQuery}`).then(
      (r) => {
        if (cancelled) return
        setFocusList(r?.focus_list ?? [])
        setFocusLoading(false)
      }
    )
    return () => {
      cancelled = true
    }
  }, [latestExam, tidQuery])

  // KPI 统计：当前学科最近考试 stats（单学科化）
  const [scopeStats, setScopeStats] = useState<ExamDetailStats | undefined>(undefined)
  const [scopeStatsLoading, setScopeStatsLoading] = useState(false)
  useEffect(() => {
    let cancelled = false
    if (!latestExam) {
      setScopeStats(undefined)
      return
    }
    setScopeStatsLoading(true)
    safeJson<ExamDetailResponse>(`/api/exams/${latestExam.id}${tidQuery}`).then((r) => {
      if (cancelled) return
      setScopeStats(r?.stats)
      setTeachingSubject(r?.subject ?? null)
      setScopeStatsLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [latestExam, tidQuery])

  // 总览态：拉 overview（单学科化）
  useEffect(() => {
    if (!isAll) return
    let cancelled = false
    setOverviewLoading(true)
    safeJson<OverviewResponse>('/api/dashboard/overview').then((r) => {
      if (cancelled) return
      setOverview(r)
      if (r?.teaching_subject) setTeachingSubject(r.teaching_subject)
      setOverviewLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [isAll])

  const examCountSeries = useMemo(() => {
    if (exams.length === 0) return []
    const ordered = [...exams].reverse()
    return ordered.map((_, i) => ({ v: i + 1 }))
  }, [exams])

  const focusSeries = useMemo(() => focusHistory.map((v) => ({ v })), [focusHistory])

  const subjectLabel = teachingSubject ?? '当前学科'
  const scoreBasisLabel =
    scopeStats?.score_basis === 'grade_score' ? '等级分' : '原始分'
  // 首次使用：无任何教学班 → 引导去配置
  const noClassesAtAll = !scopeLoading && scopeClasses.length === 0

  return (
    <div className="space-y-6">
      {/* 顶部欢迎区 + 班级范围选择 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {isAll ? '仪表盘·总览' : currentClass ? `仪表盘·${formatTeachingClass(currentClass)}` : '仪表盘'}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {isAll
              ? `任课教师 · ${subjectLabel} · 我教的所有班级数据概览`
              : currentClass
              ? `任课教师 · ${subjectLabel} · ${formatTeachingClass(currentClass)} 班级数据概览`
              : `任课教师 · ${subjectLabel} 的班级数据概览`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {!isAll && (
            <Button variant="outline" size="sm" onClick={() => setCurrent('all')}>
              <ArrowLeft className="h-4 w-4" />
              返回总览
            </Button>
          )}
          <ClassScopePicker compact />
          <span className="hidden text-sm text-slate-500 lg:inline">
            {todayString()}
          </span>
          <Button asChild>
            <Link href="/upload">
              <Upload className="h-4 w-4" />
              上传新成绩
            </Link>
          </Button>
        </div>
      </div>

      {/* 首次使用引导：无任何教学班 */}
      {noClassesAtAll && (
        <Card className="border-brand-500/30 bg-brand-50/60">
          <CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-base text-slate-900">
                还没有配置教学班
              </CardTitle>
              <CardDescription className="mt-1">
                先创建你教的班级（行政班 / 走班），仪表盘与各分析页才能按班级展示。
              </CardDescription>
            </div>
            <Button asChild variant="default">
              <Link href="/settings/classes">
                <School className="h-4 w-4" />
                前往配置班级
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {/* 初始化提示：未上传任何成绩 */}
      {showUploadPrompt && !noClassesAtAll && (
        <Card className="border-brand-500/20 bg-brand-50/50">
          <CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-base text-slate-900">
                请先上传一份学生分数表完成初始化
              </CardTitle>
              <CardDescription className="mt-1">
                未识别到当前班级，上传后会自动绑定。
              </CardDescription>
            </div>
            <Button asChild variant="default">
              <Link href="/upload">
                <Upload className="h-4 w-4" />
                前往上传
              </Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {/* 本周关注（主动提醒，单学科化） */}
      <WeeklyFocusCard teachingClassId={tidParam ?? undefined} />

      {/* KPI 行（单学科化：当前学科均分 / 最高·最低或有效人数 / 班内名次区间 / 重点关注） */}
      {loading || scopeStatsLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          <KpiCard
            title={`${subjectLabel}均分（${scoreBasisLabel}）`}
            icon={<ClipboardList className="h-4 w-4" />}
            value={formatNumber(scopeStats?.avg)}
            spark={examCountSeries}
          />
          <KpiCard
            title="最高·最低"
            icon={<School className="h-4 w-4" />}
            value={
              scopeStats?.max != null || scopeStats?.min != null
                ? `${formatNumber(scopeStats?.max)} / ${formatNumber(scopeStats?.min)}`
                : scopeStats?.total_students != null
                ? `${scopeStats.total_students} 人`
                : '—'
            }
          />
          <KpiCard
            title={isAll ? '年级名次区间' : '班内名次区间'}
            icon={<CalendarDays className="h-4 w-4" />}
            value={formatRankRange(scopeStats)}
          />
          <KpiCard
            title="重点关注"
            icon={<AlertCircle className="h-4 w-4" />}
            value={focusLoading ? '…' : focusList.length}
            spark={focusSeries}
            valueTone={focusList.length > 0 ? 'warning' : 'default'}
          />
        </div>
      )}

      {/* 主体两列 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 左：总览态=我的班级总览（单学科 subject_avg）；分班态=考试时间线 */}
        {isAll ? (
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-4 w-4" />
                我的班级总览
              </CardTitle>
              <CardDescription>
                {overview
                  ? `${subjectLabel} · 共 ${overview.overall.class_count} 个班 · ${overview.overall.total_students} 名学生`
                  : '点击任一班级进入分班视图'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {overviewLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-16 w-full" />
                  ))}
                </div>
              ) : !overview || overview.classes.length === 0 ? (
                <EmptyClasses />
              ) : (
                <ul className="space-y-2">
                  {overview.classes.map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => setCurrent(c.teaching_class_id)}
                        className="group flex w-full flex-col gap-2 rounded-lg border border-slate-100 p-3 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-slate-900 group-hover:text-brand-600">
                              {formatTeachingClass({ grade: c.grade, label: c.label }) ?? c.label}
                            </span>
                            <Badge variant="outline" className="font-normal text-slate-500">
                              {c.kind}
                            </Badge>
                            {c.subject && (
                              <Badge variant="outline" className="font-normal text-slate-500">
                                {c.subject}
                              </Badge>
                            )}
                          </div>
                          <div className="mt-0.5 truncate text-xs text-slate-500">
                            {c.member_count} 人
                            {c.latest_exam ? ` · 最近：${truncate(c.latest_exam.name, 16)}` : ' · 暂无考试'}
                          </div>
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <Badge variant="outline" className="font-normal">
                            {c.score_basis === 'grade_score' ? '等级' : '原始'} {formatNumber(c.subject_avg)}
                          </Badge>
                          <Badge
                            variant="outline"
                            className={cn(
                              'font-normal',
                              c.focus_count > 0
                                ? 'border-warning-300 text-warning-600'
                                : 'text-slate-500'
                            )}
                          >
                            关注 {c.focus_count}
                          </Badge>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>考试时间线</CardTitle>
              <CardDescription>
                {currentClass
                  ? `${subjectLabel} · ${formatTeachingClass(currentClass)} · 按时间倒序`
                  : `${subjectLabel} · 按时间倒序展示已建档考试`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-4">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : exams.length === 0 ? (
                <EmptyExams />
              ) : (
                <ol className="relative ml-3 border-l border-slate-200">
                  {exams.map((exam) => (
                    <li key={exam.id} className="relative pl-6 pb-5 last:pb-0">
                      <span className="absolute -left-[7px] top-2 h-3 w-3 rounded-full bg-brand-500 ring-4 ring-white" />
                      <Link
                        href={`/exam/${exam.id}`}
                        className="group flex flex-col gap-2 rounded-lg px-2 py-1 -mx-2 transition-colors hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <div>
                          <div className="font-medium text-slate-900 group-hover:text-brand-600">
                            {exam.name}
                          </div>
                          <div className="mt-0.5 text-xs text-slate-500">
                            {`高${exam.grade}`}
                            {exam.exam_date ? ` · ${exam.exam_date}` : ''}
                            {exam.exam_type ? ` · ${exam.exam_type}` : ''}
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Badge variant="outline" className="font-normal">
                            {subjectLabel}均分 {formatNumber(examStatsById[exam.id]?.avg)}
                          </Badge>
                          <Badge variant="outline" className="font-normal">
                            班内名次 {formatRankRange(examStatsById[exam.id])}
                          </Badge>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
        )}

        {/* 右：重点关注速览（单学科化） */}
        <Card className="lg:col-span-1">
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div className="space-y-1.5">
              <CardTitle>
                {isAll ? '重点关注（最近一次·全部班）' : '重点关注（最近一次）'}
              </CardTitle>
              <CardDescription>
                {isAll ? `${subjectLabel}·所有班并集预警名单` : `${subjectLabel}·当前班级预警名单`}
              </CardDescription>
            </div>
            {latestExam && (
              <span className="text-xs text-slate-400">
                {truncate(latestExam.name, 10)}
              </span>
            )}
          </CardHeader>
          <CardContent>
            {loading || focusLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : focusList.length === 0 ? (
              <EmptyFocus />
            ) : (
              <ul className="space-y-1">
                {focusList.slice(0, 5).map((s) => {
                  const { label, tone } = classifyIssue(s.issues)
                  const chip = formatClassChip(s.class_label)
                  return (
                    <li key={s.student_id}>
                      <Link
                        href={`/student/${s.student_id}`}
                        className="flex items-center gap-3 rounded-lg p-2 -mx-2 transition-colors hover:bg-slate-50"
                      >
                        <Avatar className="h-9 w-9">
                          <AvatarFallback>
                            {(s.name?.[0] ?? s.student_id.slice(-1) ?? '?').toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="truncate font-medium text-slate-900">
                              {s.name || s.student_id}
                            </span>
                            {chip && (
                              <Badge
                                variant="outline"
                                className="shrink-0 border-brand-200 bg-brand-50 px-1.5 py-0 text-[10px] font-normal text-brand-700"
                              >
                                {chip}
                              </Badge>
                            )}
                          </div>
                          <div className="truncate text-xs text-slate-500">
                            {s.student_id}
                          </div>
                        </div>
                        <Badge
                          variant="outline"
                          className={cn('shrink-0', issueToneClass(tone))}
                        >
                          {label}
                        </Badge>
                      </Link>
                    </li>
                  )
                })}
              </ul>
            )}
          </CardContent>
          {!loading && !focusLoading && focusList.length > 0 && latestExam && (
            <div className="border-t border-slate-100 p-3">
              <Button asChild variant="ghost" size="sm" className="w-full justify-center">
                <Link href={`/exam/${latestExam.id}`}>查看全部 →</Link>
              </Button>
            </div>
          )}
        </Card>
      </div>

      {/* 数据备份 */}
      <BackupCard />
    </div>
  )
}

interface KpiCardProps {
  title: string
  icon: React.ReactNode
  value: string | number
  spark?: Array<{ v: number }>
  valueTone?: 'default' | 'warning'
}

function KpiCard({ title, icon, value, spark, valueTone = 'default' }: KpiCardProps) {
  const showSpark = spark && spark.length >= 2
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription className="flex items-center gap-2 text-slate-500">
          {icon}
          <span>{title}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="pb-4">
        <div className="flex items-end justify-between gap-3">
          <CardTitle
            className={cn(
              'text-3xl font-semibold tracking-tight',
              valueTone === 'warning' ? 'text-warning-500' : 'text-slate-900'
            )}
          >
            {value}
          </CardTitle>
          {showSpark && (
            <div className="h-8 w-24">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={spark} margin={{ top: 4, bottom: 4, left: 0, right: 0 }}>
                  <Line
                    type="monotone"
                    dataKey="v"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function EmptyExams() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
      <CalendarOff className="h-10 w-10 text-slate-300" />
      <p className="text-sm text-slate-500">暂无考试数据</p>
      <Button asChild variant="outline" size="sm">
        <Link href="/upload">
          <Upload className="h-4 w-4" />
          前往上传
        </Link>
      </Button>
    </div>
  )
}

function EmptyFocus() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <CheckCircle2 className="h-10 w-10 text-success-500" />
      <p className="text-sm text-slate-500">暂无重点关注</p>
    </div>
  )
}

function EmptyClasses() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
      <School className="h-10 w-10 text-slate-300" />
      <p className="text-sm text-slate-500">尚未配置教学班</p>
      <Button asChild variant="outline" size="sm">
        <Link href="/settings/classes">
          <School className="h-4 w-4" />
          前往配置
        </Link>
      </Button>
    </div>
  )
}
