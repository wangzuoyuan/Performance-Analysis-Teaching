'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import {
  LineChart,
  Line,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis as RXAxis,
  YAxis as RYAxis,
} from 'recharts'
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronLeft,
  Hash,
  Minus,
  TrendingUp,
} from 'lucide-react'

import TrendLineChart from '@/components/TrendLineChart'
import HomeworkCard from '@/components/HomeworkCard'
import StudentNotes from '@/components/StudentNotes'
import { cn } from '@/lib/utils'
import { useClassScope, formatTeachingClass } from '@/lib/class-scope'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface ScoreTrendPoint {
  exam_id: number
  exam_name: string
  exam_date?: string | null
  grade?: number | null
  subject: string
  raw_score?: number | null
  grade_score?: number | null
  grade_percentile?: number | null
  class_label?: string | null
  scope_rank?: number | null
  rank_basis?: string | null
}

interface StudentProfile {
  student_id: string
  identity_id?: string | null
  all_student_ids?: string[]
  name: string
  teaching_subject?: string | null
  has_cross_year?: boolean
  grades?: number[]
  class_num?: number | null
  class_label?: string | null
  teaching_class_id?: number | null
  xueji_code?: number | null
  score_trend: ScoreTrendPoint[]
}

const SIGNIFICANT_PCT = 0.1
const DASH = '—'

const GRADE_LABEL: Record<number, string> = { 1: '高一', 2: '高二', 3: '高三' }
function gradeLabel(g: number | null | undefined): string | null {
  if (g === null || g === undefined) return null
  return GRADE_LABEL[g] ?? `高${g}`
}

function safeNum(v: unknown): number | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v))) return Number(v)
  return null
}

function formatPercent(v: number | null | undefined): string {
  const n = safeNum(v)
  if (n === null) return DASH
  return `${Math.round(n * 100)}%`
}

function nameInitial(name: string): string {
  if (!name) return '?'
  return name.trim().charAt(0)
}

/**
 * 判断趋势主指标：高二/高三选考学科（物化生政史地）用 grade_score；
 * 语数英及高一单科用 grade_percentile（越小越好）。
 */
function trendMetric(point: ScoreTrendPoint): {
  key: 'grade_score' | 'grade_percentile' | 'raw_score'
  value: number | null
  invert: boolean
} {
  const grade = point.grade
  const subject = point.subject
  const isElective = grade != null && grade >= 2 &&
    ['物理', '化学', '生物', '政治', '历史', '地理'].includes(subject)
  if (isElective) {
    return { key: 'grade_score', value: safeNum(point.grade_score), invert: false }
  }
  const pct = safeNum(point.grade_percentile)
  if (pct !== null) {
    return { key: 'grade_percentile', value: pct, invert: true }
  }
  return { key: 'raw_score', value: safeNum(point.raw_score), invert: false }
}

function DeltaArrow({
  current,
  previous,
  invert = false,
  threshold = 0,
}: {
  current: number | null
  previous: number | null
  invert?: boolean
  threshold?: number
}) {
  if (current === null || previous === null) {
    return <span className="text-slate-400">{DASH}</span>
  }
  const diff = current - previous
  const absDiff = Math.abs(diff)
  if (absDiff <= threshold) {
    return (
      <span className="inline-flex items-center gap-1 text-slate-500">
        <Minus className="h-3.5 w-3.5" />
        持平
      </span>
    )
  }
  const improved = invert ? diff < 0 : diff > 0
  const Icon = improved ? ArrowUpRight : ArrowDownRight
  const cls = improved ? 'text-success-500' : 'text-danger-500'
  const display = `${diff > 0 ? '+' : ''}${diff}`
  return (
    <span className={cn('inline-flex items-center gap-1 font-medium', cls)}>
      <Icon className="h-3.5 w-3.5" />
      {display}
    </span>
  )
}

function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}

function StudentDetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-5 w-20" />
      <Card>
        <CardContent className="flex items-center gap-4 py-6">
          <Skeleton className="h-16 w-16 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-56" />
          </div>
          <Skeleton className="h-7 w-24" />
        </CardContent>
      </Card>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-3 py-6">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-8 w-20" />
              <Skeleton className="h-3 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-48" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-64 w-full" />
        </CardContent>
      </Card>
    </div>
  )
}

export default function StudentPage() {
  const params = useParams<{ id: string }>()
  const studentId = Array.isArray(params?.id) ? params?.id[0] : params?.id
  const { scopeParam } = useClassScope()

  const [profile, setProfile] = useState<StudentProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // scopeParam 变化（切换教学班）时重新请求
  const tcId = scopeParam().teaching_class_id

  useEffect(() => {
    if (!studentId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    const sp = new URLSearchParams()
    if (tcId != null) sp.set('teaching_class_id', String(tcId))
    const qs = sp.toString()
    fetch(`/api/students/${studentId}${qs ? `?${qs}` : ''}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data: StudentProfile) => {
        if (!cancelled) setProfile(data)
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || '加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [studentId, tcId])

  const compareByExamDate = (
    a: { exam_id: number; exam_date?: string | null },
    b: { exam_id: number; exam_date?: string | null }
  ) => {
    const da = a.exam_date ?? ''
    const db = b.exam_date ?? ''
    if (da !== db) return da < db ? -1 : 1
    return a.exam_id - b.exam_id
  }

  const scoreTrend = useMemo<ScoreTrendPoint[]>(() => {
    if (!profile?.score_trend) return []
    return [...profile.score_trend].sort(compareByExamDate)
  }, [profile])

  const subject = profile?.teaching_subject ?? null

  // KPI：取最新两个趋势点
  const kpi = useMemo(() => {
    const last = scoreTrend[scoreTrend.length - 1] || null
    const prev = scoreTrend.length >= 2 ? scoreTrend[scoreTrend.length - 2] : null
    const lastMetric = last ? trendMetric(last) : null
    const prevMetric = prev ? trendMetric(prev) : null
    return {
      metricNow: lastMetric?.value ?? null,
      metricPrev: prevMetric?.value ?? null,
      metricKey: lastMetric?.key ?? null,
      metricInvert: lastMetric?.invert ?? false,
      scopeRankNow: safeNum(last?.scope_rank),
      scopeRankPrev: safeNum(prev?.scope_rank),
      percentileNow: safeNum(last?.grade_percentile),
      percentilePrev: safeNum(prev?.grade_percentile),
      rawScoreNow: safeNum(last?.raw_score),
      gradeScoreNow: safeNum(last?.grade_score),
    }
  }, [scoreTrend])

  // 学段履历
  const crossYearEntries = useMemo(() => {
    const ids = profile?.all_student_ids ?? []
    if (ids.length <= 1) return []
    const grades = Array.from(
      new Set(
        (profile?.score_trend ?? [])
          .map((p) => p.grade ?? null)
          .filter((g): g is number => g !== null && g !== undefined)
      )
    ).sort((a, b) => a - b)
    if (grades.length > 0 && grades.length === ids.length) {
      return grades.map((g, i) => ({ grade: g, studentId: ids[i] }))
    }
    return grades.length > 0
      ? grades.map((g) => ({ grade: g, studentId: null }))
      : ids.map((sid) => ({ grade: null, studentId: sid }))
  }, [profile])

  if (loading) {
    return <StudentDetailSkeleton />
  }

  if (error || !profile) {
    return (
      <div className="space-y-6">
        <Link
          href="/student"
          className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"
        >
          <ChevronLeft className="h-4 w-4" />
          返回
        </Link>
        <Card>
          <CardContent className="py-10">
            <EmptyState
              title="加载学生数据失败"
              hint={error || '请稍后重试，或确认该学号是否存在。'}
            />
          </CardContent>
        </Card>
      </div>
    )
  }

  const classNum = profile.class_num ?? null
  const latestGrade =
    scoreTrend.length > 0 ? scoreTrend[scoreTrend.length - 1].grade ?? null : null

  const teachingClassText = formatTeachingClass(
    latestGrade !== null && profile.class_label
      ? { grade: latestGrade, label: profile.class_label }
      : null
  )
  const classHeaderText = teachingClassText ?? (classNum !== null ? `${classNum}班` : null)

  // 趋势图数据
  const sparkData = scoreTrend.map((p) => {
    const m = trendMetric(p)
    return { name: p.exam_name, value: m.value ?? undefined }
  })
  const hasSparkData = sparkData.some((d) => d.value !== undefined)

  // KPI 标签
  const metricLabel =
    kpi.metricKey === 'grade_score'
      ? '最新等级分'
      : kpi.metricKey === 'grade_percentile'
        ? '最新年级百分位'
        : '最新原始分'

  return (
    <div className="space-y-6">
      {/* 返回 + 导出 */}
      <div className="flex items-center justify-between">
        <Link
          href="/student"
          className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"
        >
          <ChevronLeft className="h-4 w-4" />
          返回
        </Link>
        {studentId && (
          <Link href={`/student/${studentId}/report`}>
            <span className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">
              导出家长会一页纸
            </span>
          </Link>
        )}
      </div>

      {/* 学生卡 */}
      <Card>
        <CardContent className="flex flex-col gap-4 py-6 md:flex-row md:items-center">
          <Avatar className="h-16 w-16">
            <AvatarFallback className="bg-brand-50 text-lg font-semibold text-brand-700">
              {nameInitial(profile.name)}
            </AvatarFallback>
          </Avatar>
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
              {profile.name || DASH}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              学号 {profile.student_id || DASH}
              {' · '}
              {classHeaderText ?? DASH}
              {' · '}
              {latestGrade ? gradeLabel(latestGrade) : DASH}
            </p>
            {subject && (
              <p className="mt-0.5 text-xs text-brand-600">
                任教学科：{subject}
              </p>
            )}
            {crossYearEntries.length > 0 && (
              <p className="mt-1 flex flex-wrap items-center gap-x-1 text-xs text-slate-400">
                <span className="font-medium text-slate-500">学段履历：</span>
                {crossYearEntries.map((e, i) => (
                  <span key={`${e.grade ?? 'g'}-${e.studentId ?? 's'}-${i}`}>
                    {i > 0 && <span className="text-slate-300"> · </span>}
                    {gradeLabel(e.grade) ?? '（年级未知）'}
                    {e.studentId ? ` ${e.studentId}` : ''}
                  </span>
                ))}
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* KPI 行 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="py-5">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Hash className="h-4 w-4" />
              最新教学班排名
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="text-3xl font-semibold text-slate-900">
                {kpi.scopeRankNow !== null ? kpi.scopeRankNow : DASH}
              </span>
              <DeltaArrow
                current={kpi.scopeRankNow}
                previous={kpi.scopeRankPrev}
                invert
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="py-5">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <TrendingUp className="h-4 w-4" />
              {metricLabel}
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="text-3xl font-semibold text-slate-900">
                {kpi.metricKey === 'grade_percentile' && kpi.metricNow !== null
                  ? formatPercent(kpi.metricNow)
                  : kpi.metricNow !== null
                    ? kpi.metricNow
                    : DASH}
              </span>
              <DeltaArrow
                current={kpi.metricNow}
                previous={kpi.metricPrev}
                invert={kpi.metricInvert}
                threshold={kpi.metricKey === 'grade_percentile' ? SIGNIFICANT_PCT : 0}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="py-5">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Badge variant="secondary" className="text-xs">
                最新
              </Badge>
              原始分 / 等级分
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="text-3xl font-semibold text-slate-900">
                {kpi.rawScoreNow !== null ? kpi.rawScoreNow : DASH}
              </span>
              <span className="text-sm text-slate-400">
                等级分 {kpi.gradeScoreNow !== null ? kpi.gradeScoreNow : DASH}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 作业缺交（仅作业花名册内学生显示） */}
      {studentId && <HomeworkCard studentId={studentId} />}

      {/* 成长 / 谈话档案 */}
      {studentId && <StudentNotes studentId={studentId} />}

      {/* 单科趋势图 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {subject ? `${subject}` : '单科'}成绩趋势
          </CardTitle>
        </CardHeader>
        <CardContent>
          {hasSparkData ? (
            <>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={sparkData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <RXAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <RYAxis
                    reversed={kpi.metricInvert}
                    tick={{ fontSize: 11 }}
                  />
                  <RTooltip
                    contentStyle={{ fontSize: 12 }}
                    formatter={(v: number | string) =>
                      typeof v === 'number' && kpi.metricKey === 'grade_percentile'
                        ? `${Math.round(v * 100)}%`
                        : v
                    }
                    labelFormatter={(label) => String(label)}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    name={
                      kpi.metricKey === 'grade_score'
                        ? '等级分'
                        : kpi.metricKey === 'grade_percentile'
                          ? '年级百分位'
                          : '原始分'
                    }
                    stroke="#2563eb"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
              <p className="mt-2 text-xs text-slate-400">
                {kpi.metricKey === 'grade_score'
                  ? '高二/高三选考学科用等级分判断趋势（越高越好）'
                  : kpi.metricKey === 'grade_percentile'
                    ? '语数英及高一单科用年级百分位判断趋势（越小越好）'
                    : '原始分趋势（越高越好）'}
                ；排名按教学班成员集合统计。
              </p>
            </>
          ) : (
            <EmptyState title="趋势图数据待补" hint="尚无当前学科考试记录" />
          )}
        </CardContent>
      </Card>

      {/* 历次考试明细 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            历次{subject ?? ''}考试明细
          </CardTitle>
        </CardHeader>
        <CardContent>
          {scoreTrend.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>考试</TableHead>
                    <TableHead>日期</TableHead>
                    <TableHead className="text-right">原始分</TableHead>
                    <TableHead className="text-right">等级分</TableHead>
                    <TableHead className="text-right">百分位</TableHead>
                    <TableHead className="text-right">教学班</TableHead>
                    <TableHead className="text-right">班内排名</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...scoreTrend].reverse().map((p) => {
                    const raw = safeNum(p.raw_score)
                    const gs = safeNum(p.grade_score)
                    const pct = safeNum(p.grade_percentile)
                    const rank = safeNum(p.scope_rank)
                    return (
                      <TableRow key={p.exam_id} className="hover:bg-slate-50">
                        <TableCell className="font-medium">{p.exam_name}</TableCell>
                        <TableCell className="text-slate-500">
                          {p.exam_date || DASH}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {raw !== null ? raw : DASH}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {gs !== null ? gs : DASH}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {pct !== null ? formatPercent(pct) : DASH}
                        </TableCell>
                        <TableCell>
                          {p.class_label ? (
                            <Badge variant="secondary">{p.class_label}</Badge>
                          ) : (
                            <span className="text-slate-400">{DASH}</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {rank !== null ? rank : DASH}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState title="暂无考试记录" />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
