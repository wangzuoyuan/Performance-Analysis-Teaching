'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  ChevronRight,
  GraduationCap,
  Search,
  TrendingUp,
  Upload,
  Users,
} from 'lucide-react'

import { ClassScopePicker } from '@/components/ClassScopePicker'
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
import { useClassScope, formatClassChip } from '@/lib/class-scope'
import { formatGradeLabel } from '@/lib/labels'

interface StudentRow {
  student_id: string
  name: string
  class_label?: string | null
  teaching_class_id?: number | null
  grades?: number[]
  latest_exam_id?: number | null
  latest_total_score?: number | null
  latest_xueji_rank?: number | null
}

interface StudentsResponse {
  students: StudentRow[]
  count: number
  latest_exam?: { id: number; name: string } | null
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

function formatInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '—'
  return String(Math.round(Number(n)))
}

function gradeLabel(grades?: number[] | null): string {
  if (!grades || grades.length === 0) return '—'
  return grades.map((g) => formatGradeLabel(g)).join(' / ')
}

export default function StudentSearchPage() {
  const { scopeParam, loading: scopeLoading } = useClassScope()
  const [students, setStudents] = useState<StudentRow[]>([])
  const [count, setCount] = useState(0)
  const [latestExam, setLatestExam] = useState<{ id: number; name: string } | null>(null)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [loading, setLoading] = useState(true)

  // 搜索框防抖
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      const param = scopeParam()
      const sp = new URLSearchParams()
      if (param.teaching_class_id != null) {
        sp.set('teaching_class_id', String(param.teaching_class_id))
      }
      if (debouncedQuery) {
        sp.set('q', debouncedQuery)
      }
      const qs = sp.toString()
      const url = `/api/students${qs ? `?${qs}` : ''}`
      const res = await safeJson<StudentsResponse>(url)
      if (cancelled) return

      if (res) {
        setStudents(res.students ?? [])
        setCount(res.count ?? res.students?.length ?? 0)
        setLatestExam(res.latest_exam ?? null)
      } else {
        setStudents([])
        setCount(0)
        setLatestExam(null)
      }
      setLoading(false)
    }

    load()
    return () => {
      cancelled = true
    }
  }, [scopeParam, debouncedQuery])

  const rankedCount = useMemo(
    () => students.filter((s) => s.latest_xueji_rank != null).length,
    [students],
  )

  const scopeBusy = loading || scopeLoading

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            学生检索
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            按姓名或学号查找学生画像，支持按教学班筛选
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <ClassScopePicker />
          <Button asChild>
            <Link href="/upload">
              <Upload className="h-4 w-4" />
              上传新成绩
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <SummaryCard
          icon={<Users className="h-4 w-4" />}
          label="学生数"
          value={scopeBusy ? '…' : String(count)}
        />
        <SummaryCard
          icon={<TrendingUp className="h-4 w-4" />}
          label="有排名记录"
          value={scopeBusy ? '…' : String(rankedCount)}
        />
        <SummaryCard
          icon={<GraduationCap className="h-4 w-4" />}
          label="最近考试覆盖"
          value={scopeBusy ? '…' : latestExam?.name ?? '—'}
        />
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <CardTitle>学生名单</CardTitle>
            <CardDescription>
              默认按最近一次考试的学籍名次排序，点击姓名进入学生趋势页。
            </CardDescription>
          </div>
          <div className="relative w-full sm:w-80">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="按姓名 / 学号搜索"
              className="pl-9"
            />
          </div>
        </CardHeader>
        <CardContent>
          {scopeBusy ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : students.length === 0 ? (
            <EmptyState />
          ) : (
            <>
              {/* 桌面宽表 */}
              <div className="hidden overflow-x-auto md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-28">学号</TableHead>
                      <TableHead>姓名</TableHead>
                      <TableHead className="w-28">教学班</TableHead>
                      <TableHead className="w-32">年级</TableHead>
                      <TableHead className="w-28 text-right">最近主三门总分</TableHead>
                      <TableHead className="w-24 text-right">学籍名次</TableHead>
                      <TableHead className="w-12" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {students.map((student) => (
                      <TableRow key={student.student_id} className="hover:bg-slate-50">
                        <TableCell className="font-mono text-xs text-slate-600">
                          {student.student_id}
                        </TableCell>
                        <TableCell>
                          <Link
                            href={`/student/${student.student_id}`}
                            className="font-medium text-slate-900 hover:text-brand-600"
                          >
                            {student.name}
                          </Link>
                        </TableCell>
                        <TableCell>
                          {formatClassChip(student.class_label) ? (
                            <Badge variant="secondary">
                              {formatClassChip(student.class_label)}
                            </Badge>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-slate-600">
                          {gradeLabel(student.grades)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatInt(student.latest_total_score)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatInt(student.latest_xueji_rank)}
                        </TableCell>
                        <TableCell>
                          <Link
                            href={`/student/${student.student_id}`}
                            aria-label={`查看${student.name}`}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-900"
                          >
                            <ChevronRight className="h-4 w-4" />
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* 移动端卡片 */}
              <div className="space-y-2 md:hidden">
                {students.map((student) => (
                  <Link
                    key={student.student_id}
                    href={`/student/${student.student_id}`}
                    className="block rounded-lg border border-slate-200 bg-white p-3 transition hover:border-brand-300 hover:bg-brand-50/40"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-medium text-slate-900">{student.name}</div>
                        <div className="mt-0.5 font-mono text-xs text-slate-500">
                          {student.student_id}
                        </div>
                      </div>
                      {formatClassChip(student.class_label) ? (
                        <Badge variant="secondary">
                          {formatClassChip(student.class_label)}
                        </Badge>
                      ) : null}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
                      <span>年级：{gradeLabel(student.grades)}</span>
                      <span>
                        主三门：
                        <span className="tabular-nums text-slate-900">
                          {formatInt(student.latest_total_score)}
                        </span>
                      </span>
                      <span>
                        名次：
                        <span className="tabular-nums text-slate-900">
                          {formatInt(student.latest_xueji_rank)}
                        </span>
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
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
      <Users className="h-10 w-10 text-slate-300" />
      <p className="text-sm text-slate-500">暂无学生数据</p>
      <Button asChild variant="outline" size="sm">
        <Link href="/upload">
          <Upload className="h-4 w-4" />
          前往上传
        </Link>
      </Button>
    </div>
  )
}
