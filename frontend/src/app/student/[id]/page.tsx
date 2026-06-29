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
  Award,
  ChevronLeft,
  Hash,
  Info,
  Minus,
  TrendingUp,
} from 'lucide-react'

import TrendLineChart from '@/components/TrendLineChart'
import HomeworkCard from '@/components/HomeworkCard'
import StudentNotes from '@/components/StudentNotes'
import { cn } from '@/lib/utils'
import { formatTeachingClass } from '@/lib/class-scope'
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface MainTrendPoint {
  exam_id: number
  exam_name: string
  grade?: number | null
  total_score?: number | null
  xueji_rank?: number | null
  grade_percentile?: number | null
  class_rank?: number | null
  total_full?: number | null
  exam_date?: string | null
}

interface SubjectTrendPoint {
  exam_id: number
  exam_name: string
  exam_date?: string | null
  subject: string
  raw_score?: number | null
  grade_percentile?: number | null
  class_avg?: number | null
}

interface StudentProfile {
  student_id: string
  /** 同一自然人的统一标识（学段履历聚合键）。 */
  identity_id?: string | null
  /** 该人跨学段的所有学号（>1 即跨学段重排号）。 */
  all_student_ids?: string[]
  name: string
  has_cross_year?: boolean
  grades?: number[]
  class_num?: number | null
  /** 当前（最新年级）所属教学班标签，如「物A1」「1」。 */
  class_label?: string | null
  /** 当前所属教学班 id。 */
  teaching_class_id?: number | null
  /** 当前教学班 grade，用于拼展示串「高二·物A1」。前端无此字段时回落最新年级。 */
  xueji_code?: number | null
  main_total_trend: MainTrendPoint[]
  subject_trend: SubjectTrendPoint[]
  five_trend?: MainTrendPoint[]
  plus3_trend?: MainTrendPoint[]
  san3_trend?: MainTrendPoint[]
  /** 每场考试主三门班级排名口径：'teaching'=教学班内、'admin'=行政班内。 */
  class_rank_basis?: Record<number, 'teaching' | 'admin'>
}

type TotalTypeKey = '主三门' | '五门' | '+3' | '3+3'

const ALL_SUBJECTS = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理']
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

function hasSubjectScore(point: SubjectTrendPoint): boolean {
  return safeNum(point.raw_score) !== null
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

function xuejiBadge(code: number | null | undefined) {
  if (code === 1) {
    return {
      label: '学籍：闵中',
      className: 'border-transparent bg-brand-50 text-brand-700',
      withCaveat: true,
    }
  }
  if (code === 3) {
    return {
      label: '学籍：文绮',
      className: 'border-transparent bg-slate-100 text-slate-700',
      withCaveat: false,
    }
  }
  if (code === 4) {
    return {
      label: '学籍：外省市/复学',
      className: 'border-transparent bg-warning-50 text-warning-700',
      withCaveat: false,
    }
  }
  return null
}

function DeltaArrow({
  current,
  previous,
  invert = false,
  threshold = 0,
}: {
  current: number | null
  previous: number | null
  /** invert=true 表示"数值越小越好"（如排名、百分位） */
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
  // 进步条件：invert 时 diff < 0（变小），非 invert 时 diff > 0
  const improved = invert ? diff < 0 : diff > 0
  const Icon = improved ? ArrowUpRight : ArrowDownRight
  const cls = improved ? 'text-success-500' : 'text-danger-500'
  const display = invert
    ? `${diff > 0 ? '+' : ''}${diff}`
    : `${diff > 0 ? '+' : ''}${diff}`
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

function SubjectSparkCard({
  subject,
  points,
}: {
  subject: string
  points: SubjectTrendPoint[]
}) {
  const sorted = points
  const latest = sorted[sorted.length - 1]
  const prev = sorted.length >= 2 ? sorted[sorted.length - 2] : null

  const latestPct = safeNum(latest?.grade_percentile)
  const prevPct = safeNum(prev?.grade_percentile)
  const latestScore = safeNum(latest?.raw_score)
  const latestAvg = safeNum(latest?.class_avg)

  const hasAnyPct = sorted.some((p) => safeNum(p.grade_percentile) !== null)

  // 趋势箭头：百分位越小越好
  let trendNode: React.ReactNode = <span className="text-slate-400">{DASH}</span>
  if (latestPct !== null && prevPct !== null) {
    const diff = latestPct - prevPct
    if (Math.abs(diff) < SIGNIFICANT_PCT) {
      trendNode = (
        <span className="inline-flex items-center gap-1 text-slate-500">
          <Minus className="h-3.5 w-3.5" />
          持平
        </span>
      )
    } else if (diff < 0) {
      trendNode = (
        <span className="inline-flex items-center gap-1 font-medium text-success-500">
          <ArrowUpRight className="h-3.5 w-3.5" />
          进步
        </span>
      )
    } else {
      trendNode = (
        <span className="inline-flex items-center gap-1 font-medium text-danger-500">
          <ArrowDownRight className="h-3.5 w-3.5" />
          退步
        </span>
      )
    }
  }

  const sparkData = sorted.map((p) => ({
    name: p.exam_name,
    pct: hasAnyPct ? safeNum(p.grade_percentile) : safeNum(p.raw_score),
  }))
  const hasSparkData = sparkData.some((d) => d.pct !== null)

  return (
    <Card>
      <CardContent className="space-y-2 pt-6">
        <div className="flex items-center justify-between">
          <div className="flex items-baseline gap-2">
            <span className="text-base font-semibold text-slate-900">{subject}</span>
            <span className="text-sm text-slate-500">
              {hasAnyPct ? formatPercent(latestPct) : DASH}
            </span>
          </div>
          {trendNode}
        </div>

        <div className="h-12 w-full">
          {hasSparkData ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={sparkData} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                <RXAxis dataKey="name" hide />
                <RYAxis hide reversed={hasAnyPct} />
                <RTooltip
                  cursor={false}
                  contentStyle={{ fontSize: 11, padding: '4px 8px' }}
                  formatter={(v: number | string) =>
                    typeof v === 'number' && hasAnyPct ? `${Math.round(v * 100)}%` : v
                  }
                  labelFormatter={(label) => String(label)}
                />
                <Line
                  type="monotone"
                  dataKey="pct"
                  name={hasAnyPct ? '年级百分位' : '原始分'}
                  stroke="#2563eb"
                  strokeWidth={1.75}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-slate-400">
              暂无数据
            </div>
          )}
        </div>

        <div className="text-xs text-slate-500">
          {latestScore !== null ? `最新 ${latestScore} 分` : `最新 ${DASH}`}
          {latestAvg !== null && ` / 班均 ${latestAvg} 分`}
        </div>

        {!hasAnyPct && (
          <div className="text-xs text-slate-400">百分位数据缺失</div>
        )}
      </CardContent>
    </Card>
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
      <Card>
        <CardContent className="py-6">
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    </div>
  )
}

export default function StudentPage() {
  const params = useParams<{ id: string }>()
  const studentId = Array.isArray(params?.id) ? params?.id[0] : params?.id

  const [profile, setProfile] = useState<StudentProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!studentId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(`/api/students/${studentId}`)
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
  }, [studentId])

  // 趋势按考试时间（exam_date，格式 YYYY-MM）升序；exam_id 仅作并列兜底。
  // 注意：不能按 exam_id 排序——上传顺序≠考试时间顺序。
  const compareByExamDate = (
    a: { exam_id: number; exam_date?: string | null },
    b: { exam_id: number; exam_date?: string | null }
  ) => {
    const da = a.exam_date ?? ''
    const db = b.exam_date ?? ''
    if (da !== db) return da < db ? -1 : 1
    return a.exam_id - b.exam_id
  }

  // 主三门趋势按考试时间升序（最早 → 最新）；表格倒序展示
  const mainTrend = useMemo<MainTrendPoint[]>(() => {
    if (!profile?.main_total_trend) return []
    return [...profile.main_total_trend].sort(compareByExamDate)
  }, [profile])

  const fiveTrend = useMemo<MainTrendPoint[]>(() => {
    if (!profile?.five_trend) return []
    return [...profile.five_trend].sort(compareByExamDate)
  }, [profile])

  const plus3Trend = useMemo<MainTrendPoint[]>(() => {
    if (!profile?.plus3_trend) return []
    return [...profile.plus3_trend].sort(compareByExamDate)
  }, [profile])

  const san3Trend = useMemo<MainTrendPoint[]>(() => {
    if (!profile?.san3_trend) return []
    return [...profile.san3_trend].sort(compareByExamDate)
  }, [profile])

  const totalColumnSpecs = useMemo(() => {
    const grades = profile?.grades || []
    const hasGradeOne = grades.includes(1)
    const hasUpperGrade = grades.some((grade) => grade === 2 || grade === 3)
    const specs: {
      type: TotalTypeKey
      scoreLabel: string
      rankLabel?: string
    }[] = []

    if (hasGradeOne || !hasUpperGrade) {
      specs.push(
        { type: '主三门', scoreLabel: '三门总分', rankLabel: '三门排名' },
        { type: '五门', scoreLabel: '五门总分', rankLabel: '五门排名' }
      )
    }
    if (hasUpperGrade) {
      if (!specs.some((spec) => spec.type === '主三门')) {
        specs.push({ type: '主三门', scoreLabel: '三门总分', rankLabel: '三门排名' })
      }
      specs.push(
        { type: '+3', scoreLabel: '+3总分' },
        { type: '3+3', scoreLabel: '3+3六门总分', rankLabel: '3+3排名' }
      )
    }

    return specs
  }, [profile])

  // 按科目分桶
  const subjectBuckets = useMemo<Record<string, SubjectTrendPoint[]>>(() => {
    const map: Record<string, SubjectTrendPoint[]> = {}
    if (!profile?.subject_trend) return map
    for (const s of profile.subject_trend) {
      if (!hasSubjectScore(s)) continue
      if (!map[s.subject]) map[s.subject] = []
      map[s.subject].push(s)
    }
    Object.keys(map).forEach((k) => {
      map[k].sort(compareByExamDate)
    })
    return map
  }, [profile])

  // 历次考试明细：按 exam_id 倒序
  const examRows = useMemo(() => {
    if (!profile) return []
    // 收集所有 exam_id（来自 main + subject）
    const examMap = new Map<
      number,
      {
        exam_id: number
        exam_name: string
        exam_date?: string | null
        subjects: Record<string, number | null>
        totals: Record<string, { score: number | null; rank: number | null }>
        total: number | null
        class_rank: number | null
        xueji_rank: number | null
      }
    >()

    const ensureExam = (p: MainTrendPoint) => {
      let entry = examMap.get(p.exam_id)
      if (!entry) {
        entry = {
          exam_id: p.exam_id,
          exam_name: p.exam_name,
          exam_date: p.exam_date ?? null,
          subjects: {},
          totals: {},
          total: null,
          class_rank: null,
          xueji_rank: null,
        }
        examMap.set(p.exam_id, entry)
      }
      return entry
    }

    const addTotal = (type: TotalTypeKey, p: MainTrendPoint) => {
      const entry = ensureExam(p)
      const score = safeNum(p.total_score)
      const rank = safeNum(p.xueji_rank)
      entry.totals[type] = { score, rank }
      if (type === '主三门') {
        entry.total = score
        entry.class_rank = safeNum(p.class_rank)
        entry.xueji_rank = rank
      }
    }

    for (const p of profile.main_total_trend || []) addTotal('主三门', p)
    for (const p of profile.five_trend || []) addTotal('五门', p)
    for (const p of profile.plus3_trend || []) addTotal('+3', p)
    for (const p of profile.san3_trend || []) addTotal('3+3', p)

    for (const s of profile.subject_trend || []) {
      let entry = examMap.get(s.exam_id)
      if (!entry) {
        entry = {
          exam_id: s.exam_id,
          exam_name: s.exam_name,
          exam_date: s.exam_date ?? null,
          subjects: {},
          totals: {},
          total: null,
          class_rank: null,
          xueji_rank: null,
        }
        examMap.set(s.exam_id, entry)
      }
      entry.subjects[s.subject] = safeNum(s.raw_score)
    }

    return Array.from(examMap.values()).sort((a, b) => compareByExamDate(b, a))
  }, [profile])

  // KPI 计算（取最新两次主三门点）
  const kpi = useMemo(() => {
    const last = mainTrend[mainTrend.length - 1] || null
    const prev = mainTrend.length >= 2 ? mainTrend[mainTrend.length - 2] : null
    return {
      classRankNow: safeNum(last?.class_rank),
      classRankPrev: safeNum(prev?.class_rank),
      xuejiRankNow: safeNum(last?.xueji_rank),
      xuejiRankPrev: safeNum(prev?.xueji_rank),
      totalNow: safeNum(last?.total_score),
      totalFull: safeNum(last?.total_full),
    }
  }, [mainTrend])

  // 主三门班排口径（取最新一场考试的 basis）—— 用于 KPI 卡标签
  const classRankBasisLabel = useMemo(() => {
    if (!profile?.class_rank_basis) return null
    const last = mainTrend[mainTrend.length - 1]
    if (!last) return null
    const basis = profile.class_rank_basis[last.exam_id]
    if (basis === 'teaching') return '教学班内排名'
    if (basis === 'admin') return '行政班内排名'
    return null
  }, [profile, mainTrend])

  // 学段履历：跨学段时，按年级列出该人用过的学号。
  // 后端 all_student_ids 仅给出学号集合；按 trend 点出现的 grade 集合对应展示。
  // 同年级可能对应多个学号（极少），这里把学号按出现年级归类——
  // 由于响应未暴露每个学号所属年级，我们退而展示「学段年级列表 + 全部学号」，
  // 仅当正好一组年级一组学号且数量相等时按顺序对应（高中阶段最常见：高一/高二各一学号）。
  const crossYearEntries = useMemo(() => {
    const ids = profile?.all_student_ids ?? []
    if (ids.length <= 1) return []
    // 出现过的年级（从带 grade 字段的总分趋势点取），升序
    const grades = Array.from(
      new Set(
        [
          ...(profile?.main_total_trend ?? []),
          ...(profile?.five_trend ?? []),
          ...(profile?.plus3_trend ?? []),
          ...(profile?.san3_trend ?? []),
        ]
          .map((p) => p.grade ?? null)
          .filter((g): g is number => g !== null && g !== undefined)
      )
    ).sort((a, b) => a - b)
    // 学号数量与年级数量相等且都 >0 → 顺序对应（高一→第一个学号……）
    if (grades.length > 0 && grades.length === ids.length) {
      return grades.map((g, i) => ({ grade: g, studentId: ids[i] }))
    }
    // 否则无法可靠对应，仅列出年级 + 学号集合
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
          href="/"
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

  const xueji = xuejiBadge(profile.xueji_code ?? null)
  const classNum = profile.class_num ?? null
  // 取最新一场考试的 grade 作为展示年级
  const latestGrade =
    mainTrend.length > 0 ? mainTrend[mainTrend.length - 1].grade ?? null : null

  // 头部班级展示：优先教学班标签（拼成「高二·物A1」），否则回退行政班号「N班」
  const teachingClassText = formatTeachingClass(
    latestGrade !== null && profile.class_label
      ? { grade: latestGrade, label: profile.class_label }
      : null
  )
  const classHeaderText = teachingClassText ?? (classNum !== null ? `${classNum}班` : null)

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-6">
        {/* 返回 + 导出 */}
        <div className="flex items-center justify-between">
          <Link
            href="/"
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
              {/* 学段履历：跨学段重排号时列出 年级→学号 */}
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
            {xueji && (
              <div className="flex items-center gap-2">
                <Badge className={xueji.className}>{xueji.label}</Badge>
                {xueji.withCaveat && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label="学籍说明"
                        className="text-slate-400 hover:text-slate-600"
                      >
                        <Info className="h-4 w-4" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">
                      闵中学籍为估算口径，存在偏差
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* KPI 行 */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Card>
            <CardContent className="py-5">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <TrendingUp className="h-4 w-4" />
                最新主三门班排
                {classRankBasisLabel && (
                  <span className="text-xs text-slate-400">（{classRankBasisLabel}）</span>
                )}
              </div>
              <div className="mt-2 flex items-baseline gap-3">
                <span className="text-3xl font-semibold text-slate-900">
                  {kpi.classRankNow !== null ? kpi.classRankNow : DASH}
                </span>
                <DeltaArrow
                  current={kpi.classRankNow}
                  previous={kpi.classRankPrev}
                  invert
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="py-5">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Hash className="h-4 w-4" />
                最新学籍年级排名
              </div>
              <div className="mt-2 flex items-baseline gap-3">
                <span className="text-3xl font-semibold text-slate-900">
                  {kpi.xuejiRankNow !== null ? kpi.xuejiRankNow : DASH}
                </span>
                <DeltaArrow
                  current={kpi.xuejiRankNow}
                  previous={kpi.xuejiRankPrev}
                  invert
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="py-5">
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Award className="h-4 w-4" />
                最新总分
              </div>
              <div className="mt-2 flex items-baseline gap-3">
                <span className="text-3xl font-semibold text-slate-900">
                  {kpi.totalNow !== null ? kpi.totalNow : DASH}
                </span>
                {kpi.totalFull !== null && (
                  <span className="text-xs text-slate-400">满分 {kpi.totalFull}</span>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 作业缺交（仅作业花名册内学生显示） */}
        {studentId && <HomeworkCard studentId={studentId} />}

        {/* 成长 / 谈话档案 */}
        {studentId && <StudentNotes studentId={studentId} />}

        {/* 主三门趋势图 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">主三门总分 + 学籍年级排名趋势</CardTitle>
          </CardHeader>
          <CardContent>
            {mainTrend.length > 0 ? (
              <>
                <TrendLineChart
                  data={mainTrend.map((p) => ({
                    exam_name: p.exam_name,
                    rank: safeNum(p.xueji_rank) ?? undefined,
                    score: safeNum(p.total_score) ?? undefined,
                  }))}
                  yDataKey="rank"
                  color="#2563eb"
                  invertY
                />
                <p className="mt-2 text-xs text-slate-400">
                  学籍排名越小越好，线越高代表排名越好；班内排名按教学班成员集合统计
                  {classRankBasisLabel ? `（当前口径：${classRankBasisLabel}）` : '，未配教学班时回退行政班'}
                </p>
              </>
            ) : (
              <EmptyState title="趋势图数据待补" hint="尚无主三门考试记录" />
            )}
          </CardContent>
        </Card>

        {/* 五门趋势（高一） */}
        {fiveTrend.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">五门总分 + 学籍年级排名趋势</CardTitle>
            </CardHeader>
            <CardContent>
              <TrendLineChart
                data={fiveTrend.map((p) => ({
                  exam_name: p.exam_name,
                  rank: safeNum(p.xueji_rank) ?? undefined,
                  score: safeNum(p.total_score) ?? undefined,
                }))}
                yDataKey="rank"
                color="#0f766e"
                invertY
              />
              <p className="mt-2 text-xs text-slate-400">
                五门 = 语文、数学、英语、物理、化学；排名越小越好
              </p>
            </CardContent>
          </Card>
        )}

        {/* +3 总分趋势（高二/高三） */}
        {plus3Trend.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">+3 总分变化趋势</CardTitle>
            </CardHeader>
            <CardContent>
              <TrendLineChart
                data={plus3Trend.map((p) => ({
                  exam_name: p.exam_name,
                  score: safeNum(p.total_score) ?? undefined,
                }))}
                yDataKey="score"
                color="#7c3aed"
              />
              <p className="mt-2 text-xs text-slate-400">
                +3 = 语数英 + 三门选考科目总分，分数越高线越高
              </p>
            </CardContent>
          </Card>
        )}

        {/* 3+3 学籍年级排名趋势（高二/高三） */}
        {san3Trend.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">3+3 六门总分 + 学籍年级排名趋势</CardTitle>
            </CardHeader>
            <CardContent>
              <TrendLineChart
                data={san3Trend.map((p) => ({
                  exam_name: p.exam_name,
                  rank: safeNum(p.xueji_rank) ?? undefined,
                }))}
                yDataKey="rank"
                color="#0891b2"
                invertY
              />
              <p className="mt-2 text-xs text-slate-400">
                学籍排名越小越好，线越高代表排名越好
              </p>
            </CardContent>
          </Card>
        )}

        {/* 单科细分 */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {ALL_SUBJECTS.map((sub) => {
            const points = subjectBuckets[sub] || []
            return <SubjectSparkCard key={sub} subject={sub} points={points} />
          })}
        </div>

        {/* 历次成绩表 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">历次考试明细</CardTitle>
          </CardHeader>
          <CardContent>
            {examRows.length > 0 ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>考试</TableHead>
                      <TableHead>日期</TableHead>
                      {ALL_SUBJECTS.map((s) => (
                        <TableHead key={s} className="text-right">
                          {s.charAt(0)}
                        </TableHead>
                      ))}
                      {totalColumnSpecs.map((spec) => (
                        <TableHead key={`${spec.type}-score`} className="text-right">
                          {spec.scoreLabel}
                        </TableHead>
                      ))}
                      {totalColumnSpecs.map((spec) => (
                        spec.rankLabel ? (
                          <TableHead key={`${spec.type}-rank`} className="text-right">
                            {spec.rankLabel}
                          </TableHead>
                        ) : null
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {examRows.map((row) => (
                      <TableRow key={row.exam_id} className="hover:bg-slate-50">
                        <TableCell className="font-medium">{row.exam_name}</TableCell>
                        <TableCell className="text-slate-500">
                          {row.exam_date || DASH}
                        </TableCell>
                        {ALL_SUBJECTS.map((s) => {
                          const v = row.subjects[s]
                          const missing = v === null || v === undefined
                          return (
                            <TableCell
                              key={s}
                              className={cn(
                                'text-right tabular-nums',
                                missing && 'bg-slate-50 text-slate-400'
                              )}
                            >
                              {missing ? DASH : v}
                            </TableCell>
                          )
                        })}
                        {totalColumnSpecs.map((spec) => {
                          const total = row.totals[spec.type]
                          const value = total?.score
                          return (
                            <TableCell key={`${spec.type}-score`} className="text-right tabular-nums font-medium">
                              {value !== null && value !== undefined ? value : DASH}
                            </TableCell>
                          )
                        })}
                        {totalColumnSpecs.map((spec) => {
                          if (!spec.rankLabel) return null
                          const total = row.totals[spec.type]
                          const value = total?.rank
                          return (
                            <TableCell key={`${spec.type}-rank`} className="text-right tabular-nums">
                              {value !== null && value !== undefined ? value : DASH}
                            </TableCell>
                          )
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyState title="暂无考试记录" />
            )}
          </CardContent>
        </Card>
      </div>
    </TooltipProvider>
  )
}
