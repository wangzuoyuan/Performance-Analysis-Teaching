'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  Bar,
  BarChart,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, ClipboardList, ListChecks, TrendingDown } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

const DASH = '—'
const PIE_COLORS = [
  '#2563eb', '#0f766e', '#7c3aed', '#db2777', '#ea580c',
  '#0891b2', '#65a30d', '#dc2626', '#9333ea', '#475569',
]

interface Kpi {
  total_misses: number
  worst_subject: { name: string; count: number }
  top_students: { name: string; count: number }[]
}
interface SubjectSlice {
  name: string
  value: number
  students: { name: string; count: number }[]
}
interface WarnItem {
  name: string
  subject: string
  streak: number
  dates: string[]
}
interface Warnings {
  serious: WarnItem[]
  warning: WarnItem[]
  counts: { serious: number; warning: number; students: number }
}

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export default function HomeworkPage() {
  const router = useRouter()
  const [kpi, setKpi] = useState<Kpi | null>(null)
  const [trend, setTrend] = useState<{ dates: string[]; counts: number[] } | null>(null)
  const [subjects, setSubjects] = useState<SubjectSlice[]>([])
  const [rankings, setRankings] = useState<{ names: string[]; counts: number[] } | null>(null)
  const [warnings, setWarnings] = useState<Warnings | null>(null)

  // 录入
  const [raw, setRaw] = useState('')
  const [date, setDate] = useState(todayStr())
  const [mode, setMode] = useState<'by_student' | 'by_subject'>('by_student')
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)

  const reload = useCallback(async () => {
    const [k, t, s, r, w] = await Promise.all([
      fetch('/api/homework/kpi').then((x) => x.json()),
      fetch('/api/homework/trend').then((x) => x.json()),
      fetch('/api/homework/subjects').then((x) => x.json()),
      fetch('/api/homework/rankings?limit=10').then((x) => x.json()),
      fetch('/api/homework/warnings').then((x) => x.json()),
    ])
    setKpi(k)
    setTrend(t)
    setSubjects(s)
    setRankings(r)
    setWarnings(w)
  }, [])

  useEffect(() => {
    reload().catch(() => setFeedback('加载数据失败'))
  }, [reload])

  async function submit() {
    if (!raw.trim()) return
    setSubmitting(true)
    setFeedback(null)
    try {
      const res = await fetch('/api/homework/records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw_text: raw, date, mode }),
      })
      const data = await res.json()
      if (data.success) {
        const errs = (data.errors || []) as string[]
        setFeedback(
          `已录入 ${data.added_count} 条${errs.length ? `，${errs.length} 条有问题：${errs.join('；')}` : ''}`
        )
        if (data.added_count > 0) setRaw('')
        await reload()
      } else {
        setFeedback(data.message || '录入失败')
      }
    } catch {
      setFeedback('录入失败，请检查后端是否运行')
    } finally {
      setSubmitting(false)
    }
  }

  const trendData = (trend?.dates || []).map((d, i) => ({
    date: d.slice(5),
    fullDate: d,
    count: trend!.counts[i],
  }))
  const rankData = (rankings?.names || []).map((n, i) => ({
    name: n,
    count: rankings!.counts[i],
  }))

  const goManage = (params: Record<string, string>) => {
    const q = new URLSearchParams(params).toString()
    router.push(`/homework/manage?${q}`)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">作业跟踪</h1>
        <div className="flex flex-wrap gap-2">
          <Link href="/homework/manage">
            <Button variant="outline" size="sm">记录管理</Button>
          </Link>
          <Link href="/homework/warnings">
            <Button variant="outline" size="sm">缺交预警</Button>
          </Link>
          <Link href="/homework/correlation">
            <Button variant="outline" size="sm">缺交 × 成绩</Button>
          </Link>
          <Link href="/homework/settings">
            <Button variant="outline" size="sm">设置</Button>
          </Link>
        </div>
      </div>

      {/* 录入 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">快速录入</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            />
            <div className="inline-flex rounded-md border border-slate-200 p-0.5 text-sm">
              <button
                onClick={() => setMode('by_student')}
                className={`rounded px-3 py-1 ${mode === 'by_student' ? 'bg-brand-50 text-brand-700' : 'text-slate-500'}`}
              >
                按学生
              </button>
              <button
                onClick={() => setMode('by_subject')}
                className={`rounded px-3 py-1 ${mode === 'by_subject' ? 'bg-brand-50 text-brand-700' : 'text-slate-500'}`}
              >
                按科目
              </button>
            </div>
          </div>
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={5}
            placeholder={
              mode === 'by_student'
                ? '每行一个学生，例如：\n卜一轩：英语粉书、数学\n吴辰轩：迟到、英语'
                : '每行一个科目/情况，例如：\n数学：卜一轩、张曦\n迟到：卜一轩、吴辰轩'
            }
            className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm font-mono leading-relaxed focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <div className="flex items-center gap-3">
            <Button onClick={submit} disabled={submitting || !raw.trim()}>
              {submitting ? '录入中…' : '录入'}
            </Button>
            {feedback && <span className="text-sm text-slate-500">{feedback}</span>}
          </div>
          <p className="text-xs text-slate-400">
            含学科关键词（英语、数学等）→ 缺交记录；其余文字（请假、迟到等）→ 特殊情况。录入后自动导出当天 Excel。
          </p>
        </CardContent>
      </Card>

      {/* KPI */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="py-5">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <ClipboardList className="h-4 w-4" />
              本学期缺交总人次
            </div>
            <div className="mt-2 text-3xl font-semibold text-slate-900">
              {kpi ? kpi.total_misses : DASH}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-5">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <TrendingDown className="h-4 w-4" />
              缺交重灾学科
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-3xl font-semibold text-slate-900">
                {kpi ? kpi.worst_subject.name : DASH}
              </span>
              {kpi && kpi.worst_subject.count > 0 && (
                <span className="text-sm text-slate-400">{kpi.worst_subject.count} 次</span>
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-5">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <AlertTriangle className="h-4 w-4" />
              连续缺交预警
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="text-3xl font-semibold text-danger-500">
                {warnings ? warnings.counts.serious : DASH}
              </span>
              <span className="text-sm text-warning-600">
                黄 {warnings ? warnings.counts.warning : DASH}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400">红=连续≥3次，黄=连续2次</p>
          </CardContent>
        </Card>
      </div>

      {/* 趋势 + 学科占比 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">每日缺交趋势</CardTitle>
          </CardHeader>
          <CardContent>
            {trendData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart
                    data={trendData}
                    margin={{ top: 5, right: 16, bottom: 5, left: 0 }}
                    onClick={(state) => {
                      const p = state?.activePayload?.[0]?.payload as { fullDate?: string } | undefined
                      if (p?.fullDate) goManage({ date: p.fullDate })
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748b' }} stroke="#e2e8f0" />
                    <YAxis tick={{ fontSize: 11, fill: '#64748b' }} stroke="#e2e8f0" allowDecimals={false} />
                    <RTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                    <Line type="monotone" dataKey="count" name="缺交人次" stroke="#2563eb" strokeWidth={2} dot={{ r: 2 }} activeDot={{ r: 5 }} />
                  </LineChart>
                </ResponsiveContainer>
                <p className="mt-1 text-xs text-slate-400">点某天可查看当天缺交明细</p>
              </>
            ) : (
              <p className="py-10 text-center text-sm text-slate-400">暂无数据</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">各科缺交占比</CardTitle>
          </CardHeader>
          <CardContent>
            {subjects.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={subjects}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      label={(e: { name?: string; value?: number }) => `${e.name} ${e.value}`}
                      onClick={(d: { name?: string }) => d?.name && goManage({ subject: d.name })}
                      style={{ cursor: 'pointer' }}
                    >
                      {subjects.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <RTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  </PieChart>
                </ResponsiveContainer>
                <p className="mt-1 text-xs text-slate-400">点某学科可查看该科缺交明细</p>
              </>
            ) : (
              <p className="py-10 text-center text-sm text-slate-400">暂无数据</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 排行 + 预警 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">缺交排行榜</CardTitle>
          </CardHeader>
          <CardContent>
            {rankData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={Math.max(220, rankData.length * 30)}>
                  <BarChart data={rankData} layout="vertical" margin={{ top: 5, right: 24, bottom: 5, left: 16 }}>
                    <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} stroke="#e2e8f0" allowDecimals={false} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: '#334155' }} stroke="#e2e8f0" width={64} />
                    <RTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                    <Bar
                      dataKey="count"
                      name="缺交次数"
                      fill="#ea580c"
                      radius={[0, 4, 4, 0]}
                      cursor="pointer"
                      onClick={(d: { name?: string }) => d?.name && goManage({ student: d.name })}
                    />
                  </BarChart>
                </ResponsiveContainer>
                <p className="mt-1 text-xs text-slate-400">点某学生可查看其缺交明细</p>
              </>
            ) : (
              <p className="py-10 text-center text-sm text-slate-400">暂无数据</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base flex items-center gap-2">
              <ListChecks className="h-4 w-4" />
              连续缺交预警
            </CardTitle>
            <Link href="/homework/warnings" className="text-sm text-brand-700 hover:underline">
              按学生/学科查看 →
            </Link>
          </CardHeader>
          <CardContent className="space-y-2">
            {warnings && (warnings.serious.length > 0 || warnings.warning.length > 0) ? (
              <>
                {[...warnings.serious, ...warnings.warning].slice(0, 6).map((w, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-md border border-slate-100 px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <Badge
                        className={
                          w.streak >= 3
                            ? 'border-transparent bg-danger-50 text-danger-600'
                            : 'border-transparent bg-warning-50 text-warning-700'
                        }
                      >
                        连续{w.streak}次
                      </Badge>
                      <span className="text-sm font-medium text-slate-800">{w.name}</span>
                      <span className="text-sm text-slate-500">{w.subject}</span>
                    </div>
                    <span className="text-xs text-slate-400">
                      {w.dates[0]?.slice(5)} ~ {w.dates[w.dates.length - 1]?.slice(5)}
                    </span>
                  </div>
                ))}
                {warnings.counts.serious + warnings.counts.warning > 6 && (
                  <Link
                    href="/homework/warnings"
                    className="block pt-1 text-center text-xs text-slate-400 hover:text-slate-600"
                  >
                    共 {warnings.counts.serious + warnings.counts.warning} 条，查看全部 →
                  </Link>
                )}
              </>
            ) : (
              <p className="py-10 text-center text-sm text-slate-400">暂无连续缺交预警</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
