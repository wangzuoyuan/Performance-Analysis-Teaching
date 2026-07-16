'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { ChevronLeft, Plus, Trash2 } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ClassScopePicker } from '@/components/ClassScopePicker'
import { useClassScope } from '@/lib/class-scope'
import { cn } from '@/lib/utils'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface Semester {
  semester_start: string
  semester_end: string
  semester_name: string
}
interface SemesterHistory {
  id: number
  name: string
  start_date: string
  end_date: string
  is_current: boolean
}
interface RosterRow {
  student_id: string
  name: string
  seat_no: number | null
  gender: string | null
  excluded: number
  record_count: number
  class_num: number | null
}

export default function HomeworkSettingsPage() {
  const { current } = useClassScope()
  const rosterRequestIdRef = useRef(0)
  const [semester, setSemester] = useState<Semester>({
    semester_start: '',
    semester_end: '',
    semester_name: '',
  })
  const [semSaved, setSemSaved] = useState<string | null>(null)
  const [semesters, setSemesters] = useState<SemesterHistory[]>([])
  const [newSemester, setNewSemester] = useState({ name: '', start_date: '', end_date: '' })
  const [roster, setRoster] = useState<RosterRow[]>([])
  const [rosterScope, setRosterScope] = useState<'all' | number | null>(null)
  const [rosterLoading, setRosterLoading] = useState(false)
  const [rosterError, setRosterError] = useState(false)
  const visibleRoster = rosterScope === current ? roster : []

  // 新增学生
  const [newName, setNewName] = useState('')
  const [newSeat, setNewSeat] = useState('')
  const [newClass, setNewClass] = useState('')

  // 花名册里最常见的班号，作为「添加学生」班号留空时的默认值
  const defaultClass = useMemo(() => {
    const counts = new Map<number, number>()
    for (const r of visibleRoster) {
      if (r.class_num != null) counts.set(r.class_num, (counts.get(r.class_num) ?? 0) + 1)
    }
    let best: number | null = null
    let bestN = 0
    for (const [cls, n] of counts) {
      if (n > bestN) {
        best = cls
        bestN = n
      }
    }
    return best
  }, [visibleRoster])

  const loadRoster = useCallback(async () => {
    const requestId = ++rosterRequestIdRef.current
    setRoster([])
    setRosterScope(null)
    setRosterLoading(true)
    setRosterError(false)
    const query = current === 'all' ? '' : `?teaching_class_id=${current}`
    try {
      const response = await fetch(`/api/homework/roster${query}`)
      if (!response.ok) throw new Error('花名册加载失败')
      const data = await response.json()
      if (requestId !== rosterRequestIdRef.current) return
      setRoster(data)
      setRosterScope(current)
    } catch {
      if (requestId === rosterRequestIdRef.current) setRosterError(true)
    } finally {
      if (requestId === rosterRequestIdRef.current) setRosterLoading(false)
    }
  }, [current])
  const loadSemesters = useCallback(async () => {
    const data = await fetch('/api/homework/semesters').then((r) => r.json())
    setSemesters(data)
  }, [])

  useEffect(() => {
    fetch('/api/homework/semester')
      .then((r) => r.json())
      .then(setSemester)
      .catch(() => {})
    loadRoster().catch(() => {})
    loadSemesters().catch(() => {})
  }, [loadRoster, loadSemesters])

  async function saveSemester() {
    setSemSaved(null)
    const res = await fetch('/api/homework/semester', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(semester),
    })
    if (res.ok) {
      const data = await res.json()
      setSemester(data)
      setSemSaved('已保存')
      setTimeout(() => setSemSaved(null), 2000)
      await loadSemesters()
    }
  }

  async function addSemester() {
    if (!newSemester.start_date || !newSemester.end_date) return
    const res = await fetch('/api/homework/semesters', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...newSemester, make_current: false }),
    })
    if (res.ok) {
      setSemesters(await res.json())
      setNewSemester({ name: '', start_date: '', end_date: '' })
    }
  }

  async function makeCurrent(id: number) {
    const res = await fetch(`/api/homework/semesters/${id}/current`, { method: 'PUT' })
    if (res.ok) {
      setSemester(await res.json())
      await loadSemesters()
    }
  }

  async function toggleExcluded(row: RosterRow) {
    await fetch(`/api/homework/roster/${row.student_id}/toggle-excluded`, { method: 'PUT' })
    await loadRoster()
  }

  async function addStudent() {
    if (!newName.trim()) return
    if (current === 'all') {
      alert('请先选择具体教学班')
      return
    }
    const classNum = newClass.trim() ? Number(newClass) : defaultClass
    if (classNum == null || Number.isNaN(classNum)) {
      alert('请填写班号（花名册为空时无法自动推断）')
      return
    }
    const res = await fetch('/api/homework/roster', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newName.trim(),
        teaching_class_id: current,
        seat_no: newSeat ? Number(newSeat) : null,
        class_num: classNum,
      }),
    })
    if (res.ok) {
      setNewName('')
      setNewSeat('')
      setNewClass('')
      await loadRoster()
    } else {
      const data = await res.json().catch(() => ({}))
      alert(data.detail || '添加失败')
    }
  }

  async function removeStudent(row: RosterRow) {
    if (!confirm(`删除 ${row.name}？会同时删除其 ${row.record_count} 条作业记录。`)) return
    await fetch(`/api/homework/roster/${row.student_id}`, { method: 'DELETE' })
    await loadRoster()
  }

  return (
    <div className="space-y-6">
      <Link
        href="/homework"
        className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"
      >
        <ChevronLeft className="h-4 w-4" />
        返回作业看板
      </Link>

      {/* 学期配置 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">学期配置</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-slate-500">
            学期起止决定看板与统计的默认时间区间。
          </p>
          <div className="flex flex-wrap items-end gap-4">
            <label className="text-sm">
              <div className="mb-1 text-slate-500">起始日期</div>
              <input
                type="date"
                value={semester.semester_start}
                onChange={(e) => setSemester({ ...semester, semester_start: e.target.value })}
                className="rounded-md border border-slate-200 px-2 py-1"
              />
            </label>
            <label className="text-sm">
              <div className="mb-1 text-slate-500">结束日期</div>
              <input
                type="date"
                value={semester.semester_end}
                onChange={(e) => setSemester({ ...semester, semester_end: e.target.value })}
                className="rounded-md border border-slate-200 px-2 py-1"
              />
            </label>
            <label className="text-sm">
              <div className="mb-1 text-slate-500">学期名称</div>
              <input
                value={semester.semester_name}
                onChange={(e) => setSemester({ ...semester, semester_name: e.target.value })}
                placeholder="2025-2026学年第二学期"
                className="w-56 rounded-md border border-slate-200 px-2 py-1"
              />
            </label>
            <Button onClick={saveSemester}>保存</Button>
            {semSaved && <span className="text-sm text-success-600">{semSaved}</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">历史学期</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 md:grid-cols-[1fr_160px_160px_auto]">
            <input value={newSemester.name} onChange={(e) => setNewSemester({ ...newSemester, name: e.target.value })}
              placeholder="学期名称" className="rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
            <input type="date" value={newSemester.start_date} onChange={(e) => setNewSemester({ ...newSemester, start_date: e.target.value })}
              className="rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
            <input type="date" value={newSemester.end_date} onChange={(e) => setNewSemester({ ...newSemester, end_date: e.target.value })}
              className="rounded-md border border-slate-200 px-2 py-1.5 text-sm" />
            <Button variant="outline" onClick={addSemester}>添加历史学期</Button>
          </div>
          <div className="space-y-2">
            {semesters.map((item) => (
              <div key={item.id} className="flex flex-col justify-between gap-2 rounded-lg border border-slate-200 p-3 sm:flex-row sm:items-center">
                <div>
                  <span className="font-medium">{item.name}</span>
                  {item.is_current && <Badge className="ml-2 border-0 bg-brand-50 text-brand-700">当前</Badge>}
                  <div className="text-xs text-slate-400">{item.start_date} 至 {item.end_date}</div>
                </div>
                {!item.is_current && <Button size="sm" variant="ghost" onClick={() => makeCurrent(item.id)}>设为当前学期</Button>}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 花名册 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle className="text-base">花名册 · 排除统计</CardTitle>
          <ClassScopePicker compact />
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-slate-500">
            打开「排除统计」的学生，其缺交不计入看板、排行、预警与相关性。
          </p>

          {/* 添加学生 */}
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={newSeat}
              onChange={(e) => setNewSeat(e.target.value)}
              placeholder="座号"
              className="w-20 rounded-md border border-slate-200 px-2 py-1 text-sm"
            />
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="姓名"
              className="w-32 rounded-md border border-slate-200 px-2 py-1 text-sm"
            />
            <input
              value={newClass}
              onChange={(e) => setNewClass(e.target.value)}
              inputMode="numeric"
              placeholder={defaultClass != null ? `班号（默认 ${defaultClass}）` : '班号'}
              className="w-32 rounded-md border border-slate-200 px-2 py-1 text-sm"
            />
            <Button variant="outline" size="sm" onClick={addStudent}
              disabled={current === 'all' || rosterScope !== current || rosterLoading || rosterError}>
              <Plus className="mr-1 h-4 w-4" />
              添加学生
            </Button>
          </div>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>座号</TableHead>
                  <TableHead>姓名</TableHead>
                  <TableHead>班级</TableHead>
                  <TableHead>性别</TableHead>
                  <TableHead className="text-right">记录数</TableHead>
                  <TableHead className="text-center">排除统计</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRoster.map((row) => (
                  <TableRow
                    key={row.student_id}
                    className={cn('hover:bg-slate-50', row.excluded && 'opacity-50')}
                  >
                    <TableCell className="text-slate-500">{row.seat_no ?? '—'}</TableCell>
                    <TableCell className="font-medium">
                      {row.name}
                      {row.excluded === 1 && (
                        <Badge className="ml-2 border-transparent bg-slate-100 text-slate-500">
                          不计入统计
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-slate-500">{row.class_num ?? '—'}</TableCell>
                    <TableCell className="text-slate-500">{row.gender ?? '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.record_count}</TableCell>
                    <TableCell className="text-center">
                      <button
                        onClick={() => toggleExcluded(row)}
                        className={cn(
                          'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                          row.excluded ? 'bg-warning-500' : 'bg-slate-200'
                        )}
                        aria-label="切换排除统计"
                      >
                        <span
                          className={cn(
                            'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
                            row.excluded ? 'translate-x-4' : 'translate-x-0.5'
                          )}
                        />
                      </button>
                    </TableCell>
                    <TableCell className="text-right">
                      <button
                        onClick={() => removeStudent(row)}
                        className="text-slate-400 hover:text-danger-500"
                        aria-label="删除学生"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {rosterLoading && <p className="text-sm text-slate-500">花名册加载中…</p>}
          {rosterError && <p className="text-sm text-danger-600">花名册加载失败，请切换班级后重试。</p>}
        </CardContent>
      </Card>
    </div>
  )
}
