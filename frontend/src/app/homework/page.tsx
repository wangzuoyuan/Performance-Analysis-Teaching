'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  AlertTriangle, Award, CalendarDays, CheckCircle2, ClipboardList,
  Medal, Search, Sparkles, UserCheck,
} from 'lucide-react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { useClassScope } from '@/lib/class-scope'

type StudentItem = {
  student_id: string
  name: string
  class_labels: string[]
  count: number
  dates?: string[]
  evaluations?: string[]
}
type StreakItem = StudentItem & { subject: string; streak: number }
type Dashboard = {
  scope: { label: string; member_count: number }
  date_range: { start: string; end: string }
  kpi: { total_misses: number; worst_subject: { name: string; count: number } }
  warnings: {
    streak: {
      serious: StreakItem[]
      warning: StreakItem[]
      counts: { serious: number; warning: number; students: number }
    }
    quality: StudentItem[]
    forgot: StudentItem[]
  }
  honors: { excellent: StudentItem[]; full_attendance: StudentItem[] }
  rankings: { missing: StudentItem[]; excellent: StudentItem[] }
  submission_rates: {
    teaching_class_id: number
    label: string
    member_count: number
    submitted: number
    expected: number
    rate: number
  }[]
  trend: { period: string; count: number }[]
  evaluation_distribution: { tone: string; label: string; count: number }[]
  heatmap: { date: string; count: number }[]
  semester_compare: { semester_id: number; name: string; misses: number; is_current: boolean }[]
}
type PreviewItem = {
  raw: string
  student_id: string
  name: string
  subject: string
  submission_status: string
  evaluation: string
  content: string
  special_type: string
}
type PreviewError = { raw: string; message: string; candidates?: { student_id: string; name: string }[] }

const CHART_COLORS = ['#2563eb', '#94a3b8', '#ef4444']

function today() {
  return new Date().toISOString().slice(0, 10)
}

function StudentName({
  item, onOpen,
}: {
  item: StudentItem
  onOpen: (item: StudentItem) => void
}) {
  return (
    <button className="text-left font-medium text-slate-800 hover:text-brand-700" onClick={() => onOpen(item)}>
      {item.name}
      {item.class_labels?.length > 0 && (
        <span className="ml-1.5 text-xs font-normal text-slate-400">{item.class_labels.join(' / ')}</span>
      )}
    </button>
  )
}

function Empty({ text = '暂无数据' }: { text?: string }) {
  return <div className="py-9 text-center text-sm text-slate-400">{text}</div>
}

export default function HomeworkPage() {
  const { current, currentClass } = useClassScope()
  const [data, setData] = useState<Dashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [student, setStudent] = useState('')
  const [groupBy, setGroupBy] = useState<'week' | 'month'>('week')

  const [entryDate, setEntryDate] = useState(today())
  const [entryMode, setEntryMode] = useState<'smart' | 'by_student' | 'by_subject'>('smart')
  const [raw, setRaw] = useState('')
  const [preview, setPreview] = useState<PreviewItem[]>([])
  const [previewErrors, setPreviewErrors] = useState<PreviewError[]>([])
  const [previewOpen, setPreviewOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState('')

  const [studentOpen, setStudentOpen] = useState(false)
  const [studentDetail, setStudentDetail] = useState<any>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ group_by: groupBy })
    if (current !== 'all') params.set('teaching_class_id', String(current))
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    if (student.trim()) params.set('student', student.trim())
    try {
      const response = await fetch(`/api/homework/dashboard?${params}`)
      if (!response.ok) throw new Error('加载失败')
      const payload = await response.json()
      setData(payload)
      if (!startDate) setStartDate(payload.date_range.start)
      if (!endDate) setEndDate(payload.date_range.end)
    } catch {
      setError('作业看板加载失败，请检查后端服务。')
    } finally {
      setLoading(false)
    }
  }, [current, endDate, groupBy, startDate, student])

  useEffect(() => {
    load()
  }, [load])

  async function previewEntry() {
    if (current === 'all' || !raw.trim()) return
    setFeedback('')
    if (entryMode !== 'smart') {
      setPreview(raw.split('\n').filter(Boolean).map((line) => ({
        raw: line, student_id: '', name: line.split(/[：:]/)[0],
        subject: entryMode === 'by_subject' ? line.split(/[：:]/)[0] : '按科目拆分',
        submission_status: '缺交', evaluation: '', content: '', special_type: '',
      })))
      setPreviewErrors([])
      setPreviewOpen(true)
      return
    }
    const response = await fetch('/api/homework/smart-input', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        raw_text: raw, date: entryDate, teaching_class_id: current, confirm: false,
      }),
    })
    const payload = await response.json()
    setPreview(payload.preview ?? [])
    setPreviewErrors(payload.errors ?? [])
    setPreviewOpen(true)
  }

  async function confirmEntry() {
    if (current === 'all') return
    setSaving(true)
    try {
      const smart = entryMode === 'smart'
      const response = await fetch(smart ? '/api/homework/smart-input' : '/api/homework/records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(smart ? {
          raw_text: raw, date: entryDate, teaching_class_id: current, confirm: true,
        } : {
          raw_text: raw, date: entryDate, teaching_class_id: current, mode: entryMode,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail?.message || payload.detail || '录入失败')
      setFeedback(`已录入 ${payload.added_count} 条记录`)
      setRaw('')
      setPreviewOpen(false)
      await load()
    } catch (reason) {
      setFeedback(reason instanceof Error ? reason.message : '录入失败')
    } finally {
      setSaving(false)
    }
  }

  async function openStudent(item: StudentItem) {
    setStudentOpen(true)
    setStudentDetail(null)
    const response = await fetch(`/api/homework/student/${item.student_id}`)
    setStudentDetail(await response.json())
  }

  const heatMax = Math.max(1, ...(data?.heatmap.map((x) => x.count) ?? [1]))
  const streakItems = [...(data?.warnings.streak.serious ?? []), ...(data?.warnings.streak.warning ?? [])]

  return (
    <div className="space-y-5 pb-10">
      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">作业仪表盘</h1>
          <p className="mt-1 text-sm text-slate-500">
            {data?.scope.label ?? (currentClass?.label || '全部（我教的班）')}
            {data ? ` · ${data.scope.member_count} 名有效学生` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/homework/manage"><Button variant="outline" size="sm">记录管理</Button></Link>
          <Link href="/homework/warnings"><Button variant="outline" size="sm">独立预警</Button></Link>
          <Link href="/homework/correlation"><Button variant="outline" size="sm">缺交 × 成绩</Button></Link>
          <Link href="/homework/settings"><Button variant="outline" size="sm">设置</Button></Link>
        </div>
      </div>

      <Card className="border-brand-100">
        <CardContent className="grid gap-4 pt-5 lg:grid-cols-[1fr_310px]">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Sparkles className="h-4 w-4 text-brand-600" />
              <span className="text-sm font-medium">智能录入</span>
              {(['smart', 'by_student', 'by_subject'] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setEntryMode(mode)}
                  className={`rounded-full px-2.5 py-1 text-xs ${entryMode === mode ? 'bg-brand-50 text-brand-700' : 'text-slate-500'}`}
                >
                  {{ smart: '姓名 + 动作', by_student: '学生：科目', by_subject: '科目：学生' }[mode]}
                </button>
              ))}
            </div>
            <textarea
              value={raw}
              onChange={(event) => setRaw(event.target.value)}
              disabled={current === 'all'}
              rows={4}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm leading-relaxed outline-none focus:border-brand-400 disabled:bg-slate-50"
              placeholder={
                current === 'all'
                  ? '请选择一个具体教学班后录入'
                  : entryMode === 'smart'
                    ? '每行一条，例如：\n王小明数学缺交订正\n李晓华物理优秀\n陈同学忘带英语作业'
                    : entryMode === 'by_student'
                      ? '王小明：数学、英语粉书'
                      : '数学：王小明、李晓华'
              }
            />
          </div>
          <div className="flex flex-col justify-between gap-3">
            <label className="text-sm text-slate-500">
              记录日期
              <input type="date" value={entryDate} onChange={(event) => setEntryDate(event.target.value)}
                className="mt-1 block w-full rounded-md border border-slate-200 px-2 py-1.5 text-slate-700" />
            </label>
            <Button onClick={previewEntry} disabled={current === 'all' || !raw.trim()}>解析并预览</Button>
            <p className="text-xs text-slate-400">姓名只在当前教学班匹配；同名学生需用学号消歧。</p>
            {feedback && <p className="text-sm text-brand-700">{feedback}</p>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-3 pt-5 md:flex-row md:items-end">
          <label className="text-xs text-slate-500">开始日期
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 block rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </label>
          <label className="text-xs text-slate-500">结束日期
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 block rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
          </label>
          <label className="min-w-48 flex-1 text-xs text-slate-500">姓名
            <div className="relative mt-1">
              <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
              <input value={student} onChange={(e) => setStudent(e.target.value)} placeholder="按姓名筛选"
                className="w-full rounded-md border border-slate-200 py-1.5 pl-8 pr-2 text-sm" />
            </div>
          </label>
          <Button variant="outline" onClick={load}>应用筛选</Button>
        </CardContent>
      </Card>

      {error && <div className="rounded-lg bg-danger-50 p-3 text-sm text-danger-600">{error}</div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: '区间缺交', value: data?.kpi.total_misses, icon: ClipboardList, tone: 'text-slate-900' },
          { label: '红色预警', value: data?.warnings.streak.counts.serious, icon: AlertTriangle, tone: 'text-danger-600' },
          { label: '黄色预警', value: data?.warnings.streak.counts.warning, icon: AlertTriangle, tone: 'text-warning-600' },
          { label: '全勤之星', value: data?.honors.full_attendance.length, icon: UserCheck, tone: 'text-success-600' },
        ].map(({ label, value, icon: Icon, tone }) => (
          <Card key={label}>
            <CardContent className="pt-5">
              <div className="flex items-center gap-2 text-xs text-slate-500"><Icon className="h-4 w-4" />{label}</div>
              <div className={`mt-2 text-3xl font-semibold ${tone}`}>{loading ? '—' : value ?? 0}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="overflow-hidden">
          <CardHeader><CardTitle className="text-base">连续缺交预警</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {streakItems.length === 0 ? <Empty /> : streakItems.slice(0, 8).map((item) => (
              <div key={`${item.student_id}-${item.subject}`} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm">
                <StudentName item={item} onOpen={openStudent} />
                <div className="flex items-center gap-2">
                  <span className="text-slate-500">{item.subject}</span>
                  <Badge className={item.streak >= 3 ? 'border-0 bg-danger-50 text-danger-600' : 'border-0 bg-warning-50 text-warning-700'}>
                    {item.streak} 次
                  </Badge>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader><CardTitle className="text-base">质量预警 · 连续负面评价</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {(data?.warnings.quality.length ?? 0) === 0 ? <Empty /> : data?.warnings.quality.slice(0, 8).map((item) => (
              <div key={item.student_id} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm">
                <StudentName item={item} onOpen={openStudent} />
                <Badge className="border-0 bg-danger-50 text-danger-600">连续 {item.count} 次</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader><CardTitle className="text-base">忘带预警 · 区间至少 3 次</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {(data?.warnings.forgot.length ?? 0) === 0 ? <Empty /> : data?.warnings.forgot.slice(0, 8).map((item) => (
              <div key={item.student_id} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm">
                <StudentName item={item} onOpen={openStudent} />
                <Badge className="border-0 bg-warning-50 text-warning-700">{item.count} 次</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Award className="h-4 w-4 text-warning-500" />优秀之星</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {(data?.honors.excellent.length ?? 0) === 0 ? <Empty /> : data?.honors.excellent.map((item) => (
              <button key={item.student_id} onClick={() => openStudent(item)} className="rounded-full bg-warning-50 px-3 py-1.5 text-sm text-warning-700">
                {item.name} · {item.count} 次
              </button>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CheckCircle2 className="h-4 w-4 text-success-600" />全勤之星</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {(data?.honors.full_attendance.length ?? 0) === 0 ? <Empty /> : data?.honors.full_attendance.map((item) => (
              <button key={item.student_id} onClick={() => openStudent(item)} className="rounded-full bg-success-50 px-3 py-1.5 text-sm text-success-700">
                {item.name}
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {([
          ['缺交排行榜', data?.rankings.missing ?? [], '缺交'],
          ['优秀排行榜', data?.rankings.excellent ?? [], '优秀'],
        ] as const).map(([title, rows, suffix]) => (
          <Card key={title}>
            <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
            <CardContent>
              {rows.length === 0 ? <Empty /> : (
                <Table>
                  <TableHeader><TableRow><TableHead>排名</TableHead><TableHead>学生</TableHead><TableHead className="text-right">次数</TableHead></TableRow></TableHeader>
                  <TableBody>{rows.map((item, index) => (
                    <TableRow key={item.student_id}>
                      <TableCell><span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs">{index + 1}</span></TableCell>
                      <TableCell><StudentName item={item} onOpen={openStudent} /></TableCell>
                      <TableCell className="text-right tabular-nums">{item.count} {suffix}</TableCell>
                    </TableRow>
                  ))}</TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader><CardTitle className="text-base">教学班提交率</CardTitle></CardHeader>
          <CardContent className="h-72">
            {(data?.submission_rates.length ?? 0) === 0 ? <Empty /> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data?.submission_rates} layout="vertical" margin={{ left: 12, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                  <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
                  <YAxis dataKey="label" type="category" width={74} />
                  <Tooltip formatter={(value) => [`${value}%`, '提交率']} />
                  <Bar dataKey="rate" fill="#2563eb" radius={[0, 5, 5, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-base">缺交趋势</CardTitle>
            <div className="flex rounded-md bg-slate-100 p-0.5 text-xs">
              {(['week', 'month'] as const).map((mode) => (
                <button key={mode} onClick={() => setGroupBy(mode)}
                  className={`rounded px-2 py-1 ${groupBy === mode ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500'}`}>
                  {mode === 'week' ? '周' : '月'}
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent className="h-72">
            {(data?.trend.length ?? 0) === 0 ? <Empty /> : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data?.trend}>
                  <defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2563eb" stopOpacity={0.28} /><stop offset="100%" stopColor="#2563eb" stopOpacity={0.02} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} width={30} />
                  <Tooltip />
                  <Area type="monotone" dataKey="count" name="缺交" stroke="#2563eb" fill="url(#trendFill)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="overflow-hidden">
          <CardHeader><CardTitle className="text-base">评价分布</CardTitle></CardHeader>
          <CardContent className="h-64">
            {(data?.evaluation_distribution.every((x) => x.count === 0)) ? <Empty /> : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data?.evaluation_distribution} dataKey="count" nameKey="label" innerRadius={48} outerRadius={82} paddingAngle={3}>
                    {data?.evaluation_distribution.map((item, index) => <Cell key={item.tone} fill={CHART_COLORS[index]} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CalendarDays className="h-4 w-4" />每日缺交热力图</CardTitle></CardHeader>
          <CardContent>
            {(data?.heatmap.length ?? 0) === 0 ? <Empty /> : (
              <div className="grid grid-cols-7 gap-2 sm:grid-cols-10 md:grid-cols-14">
                {data?.heatmap.map((item) => (
                  <button key={item.date} title={`${item.date}：${item.count} 次`}
                    className="aspect-square rounded-md text-[10px] font-medium"
                    style={{ backgroundColor: `rgba(37,99,235,${0.14 + item.count / heatMax * 0.78})`, color: item.count / heatMax > 0.55 ? 'white' : '#1e3a8a' }}>
                    {item.date.slice(8)}
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Medal className="h-4 w-4" />学期缺交对比</CardTitle></CardHeader>
        <CardContent className="h-64">
          {(data?.semester_compare.length ?? 0) === 0 ? <Empty /> : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data?.semester_compare}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="misses" name="缺交" fill="#64748b" radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>确认录入</DialogTitle>
            <DialogDescription>确认解析结果后一次性写入；存在未匹配项时不可提交。</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {preview.map((item, index) => (
              <div key={`${item.raw}-${index}`} className="grid gap-1 rounded-lg border border-slate-200 p-3 text-sm sm:grid-cols-[1fr_auto_auto]">
                <div><span className="font-medium">{item.name}</span><span className="ml-2 text-xs text-slate-400">{item.student_id}</span><div className="text-xs text-slate-400">{item.raw}</div></div>
                <Badge variant="outline">{item.special_type || item.subject}</Badge>
                <Badge className={item.submission_status === '缺交' ? 'border-0 bg-danger-50 text-danger-600' : 'border-0 bg-success-50 text-success-700'}>
                  {item.special_type || item.evaluation || item.submission_status}
                </Badge>
              </div>
            ))}
            {previewErrors.map((item, index) => (
              <div key={`${item.raw}-${index}`} className="rounded-lg bg-danger-50 p-3 text-sm text-danger-600">
                {item.raw}：{item.message}
                {item.candidates && <div className="mt-1 text-xs">{item.candidates.map((x) => `${x.name}（${x.student_id}）`).join('、')}</div>}
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>取消</Button>
            <Button onClick={confirmEntry} disabled={saving || preview.length === 0 || previewErrors.length > 0}>
              {saving ? '提交中…' : `确认录入 ${preview.length} 条`}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={studentOpen} onOpenChange={setStudentOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>学生作业统计</DialogTitle></DialogHeader>
          {!studentDetail ? <Empty text="加载中…" /> : studentDetail.error ? (
            <p className="text-sm text-danger-600">{studentDetail.error}</p>
          ) : (
            <div className="space-y-4">
              <div>
                <div className="text-lg font-semibold">{studentDetail.student.name}</div>
                <div className="text-xs text-slate-400">学号 {studentDetail.student.student_id}</div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-slate-50 p-3"><div className="text-xs text-slate-500">学期缺交</div><div className="mt-1 text-2xl font-semibold">{studentDetail.total_misses}</div></div>
                <div className="rounded-lg bg-slate-50 p-3"><div className="text-xs text-slate-500">活跃预警</div><div className="mt-1 text-2xl font-semibold">{studentDetail.active_warnings?.length ?? 0}</div></div>
              </div>
              <div className="space-y-2">
                {Object.entries(studentDetail.miss_by_subject ?? {}).map(([subjectName, count]) => (
                  <div key={subjectName} className="flex justify-between text-sm"><span>{subjectName}</span><span>{String(count)} 次</span></div>
                ))}
              </div>
              <Link href={`/student/${studentDetail.student.student_id}`}><Button variant="outline" className="w-full">打开完整学生画像</Button></Link>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
