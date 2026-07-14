'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  AlertCircle,
  CalendarDays,
  ChevronRight,
  ClipboardList,
  Hash,
  Search,
  TrendingUp,
  Upload,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ClassScopePicker } from '@/components/ClassScopePicker'
import { useClassScope } from '@/lib/class-scope'
import { formatGradeLabel } from '@/lib/labels'

interface Exam {
  id: number
  name: string
  grade: number
  semester?: string | null
  exam_date?: string | null
  exam_type?: string | null
}

interface ExamListResponse {
  exams?: Exam[]
  subject?: string | null
}

interface ExamStats {
  total_students?: number | null
  avg?: number | null
  max?: number | null
  min?: number | null
  rank_min?: number | null
  rank_max?: number | null
}

interface ExamDetailResponse {
  stats?: ExamStats
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

function formatNumber(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(digits)
}

function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return String(Math.round(Number(n)))
}

function rankRange(stats: ExamStats | undefined): string {
  if (!stats || (stats.rank_min == null && stats.rank_max == null)) return '—'
  return `${formatInt(stats.rank_min)}-${formatInt(stats.rank_max)}`
}

export default function ExamListPage() {
  // 单学科化：教学班范围由 ClassScopeProvider 统一管理，切换后整页刷新。
  const { current } = useClassScope()

  const [exams, setExams] = useState<Exam[]>([])
  const [subject, setSubject] = useState<string | null>(null)
  const [statsById, setStatsById] = useState<Record<number, ExamStats>>({})
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [scopeError, setScopeError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setScopeError(null)
      // 单学科化：teaching_class_id 由教学班上下文决定，前端不传学科。
      const tcParam = current !== 'all' ? `?teaching_class_id=${current}` : ''
      const examsRes = await safeJson<ExamListResponse>(`/api/exams${tcParam}`)
      if (cancelled) return
      if (!examsRes) {
        setScopeError('无法加载考试列表，请先在设置中配置任教科目和教学班')
        setExams([])
        setStatsById({})
        setLoading(false)
        return
      }
      const examsList = examsRes.exams ?? []
      setSubject(examsRes.subject ?? null)
      setExams(examsList)
      const detailEntries = await Promise.all(
        examsList.map((exam) =>
          safeJson<ExamDetailResponse>(
            `/api/exams/${exam.id}${current !== 'all' ? `?teaching_class_id=${current}` : ''}`,
          ).then((detail) => [exam.id, detail?.stats ?? ({} as ExamStats)] as const),
        ),
      )
      if (cancelled) return

      setStatsById(Object.fromEntries(detailEntries))
      setLoading(false)
    }

    load()
    return () => {
      cancelled = true
    }
  }, [current])

  const visibleExams = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return exams
    return exams.filter((exam) =>
      [exam.name, exam.exam_date, exam.exam_type, `高${exam.grade}`]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q)),
    )
  }, [exams, query])

  const latest = exams[0] ?? null
  const subjectLabel = subject ?? '科目'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            考试列表
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {subject ? `${subject}成绩概览` : '已建档考试与成绩概览'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ClassScopePicker compact />
          <Button asChild>
            <Link href="/upload">
              <Upload className="h-4 w-4" />
              上传新成绩
            </Link>
          </Button>
        </div>
      </div>

      {scopeError ? (
        <Card>
          <CardContent className="py-12">
            <div className="flex flex-col items-center justify-center gap-3 text-center">
              <AlertCircle className="h-10 w-10 text-amber-400" />
              <p className="text-sm text-slate-600">{scopeError}</p>
              <Button asChild variant="outline" size="sm">
                <Link href="/settings/classes">前往设置教学班</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <SummaryCard
              icon={<ClipboardList className="h-4 w-4" />}
              label="考试场次"
              value={loading ? '…' : String(exams.length)}
            />
            <SummaryCard
              icon={<CalendarDays className="h-4 w-4" />}
              label="最近考试"
              value={latest?.name ?? '—'}
            />
            <SummaryCard
              icon={<TrendingUp className="h-4 w-4" />}
              label={`${subjectLabel}平均`}
              value={latest ? formatNumber(statsById[latest.id]?.avg) : '—'}
            />
          </div>

          <Card>
            <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <CardTitle>全部考试</CardTitle>
                <CardDescription>
                  点击任意考试查看{subject ? subject : '当前学科'}学生明细和分数段分布。
                </CardDescription>
              </div>
              <div className="relative w-full sm:w-80">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="按考试名称 / 日期搜索"
                  className="pl-9"
                />
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : exams.length === 0 ? (
                <EmptyState />
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>考试</TableHead>
                        <TableHead className="w-24">年级</TableHead>
                        <TableHead className="w-28">日期</TableHead>
                        <TableHead className="w-32 text-right">{subjectLabel}平均</TableHead>
                        <TableHead className="w-32 text-right">最高 / 最低</TableHead>
                        <TableHead className="w-32 text-right">{subjectLabel}名次</TableHead>
                        <TableHead className="w-12" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleExams.map((exam) => {
                        const stats = statsById[exam.id]
                        return (
                          <TableRow key={exam.id} className="hover:bg-slate-50">
                            <TableCell>
                              <Link
                                href={`/exam/${exam.id}`}
                                className="font-medium text-slate-900 hover:text-brand-600"
                              >
                                {exam.name}
                              </Link>
                              <div className="mt-1 flex gap-1">
                                {exam.semester ? (
                                  <Badge variant="secondary">{exam.semester}</Badge>
                                ) : null}
                                {exam.exam_type ? (
                                  <Badge variant="outline">{exam.exam_type}</Badge>
                                ) : null}
                              </div>
                            </TableCell>
                            <TableCell>{formatGradeLabel(exam.grade)}</TableCell>
                            <TableCell className="text-slate-600">{exam.exam_date || '—'}</TableCell>
                            <TableCell className="text-right tabular-nums">
                              {formatNumber(stats?.avg)}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {formatInt(stats?.max)} / {formatInt(stats?.min)}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {rankRange(stats)}
                            </TableCell>
                            <TableCell>
                              <Link
                                href={`/exam/${exam.id}`}
                                aria-label={`查看${exam.name}`}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-900"
                              >
                                <ChevronRight className="h-4 w-4" />
                              </Link>
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
        </>
      )}
    </div>
  )
}

function SummaryCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <Card>
      <CardContent className="py-5">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          {icon}
          {label}
        </div>
        <div className="mt-2 truncate text-2xl font-semibold text-slate-900">
          {value}
        </div>
      </CardContent>
    </Card>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
      <Hash className="h-10 w-10 text-slate-300" />
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
