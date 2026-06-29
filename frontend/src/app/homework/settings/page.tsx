'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { ChevronLeft, Plus, Trash2 } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
interface RosterRow {
  student_id: string
  name: string
  seat_no: number | null
  gender: string | null
  excluded: number
  record_count: number
}

export default function HomeworkSettingsPage() {
  const [semester, setSemester] = useState<Semester>({
    semester_start: '',
    semester_end: '',
    semester_name: '',
  })
  const [semSaved, setSemSaved] = useState<string | null>(null)
  const [roster, setRoster] = useState<RosterRow[]>([])

  // 新增学生
  const [newName, setNewName] = useState('')
  const [newSeat, setNewSeat] = useState('')

  const loadRoster = useCallback(async () => {
    const data = await fetch('/api/homework/roster').then((r) => r.json())
    setRoster(data)
  }, [])

  useEffect(() => {
    fetch('/api/homework/semester')
      .then((r) => r.json())
      .then(setSemester)
      .catch(() => {})
    loadRoster().catch(() => {})
  }, [loadRoster])

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
    }
  }

  async function toggleExcluded(row: RosterRow) {
    await fetch(`/api/homework/roster/${row.student_id}/toggle-excluded`, { method: 'PUT' })
    await loadRoster()
  }

  async function addStudent() {
    if (!newName.trim()) return
    const res = await fetch('/api/homework/roster', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: newName.trim(),
        seat_no: newSeat ? Number(newSeat) : null,
        class_num: 6,
      }),
    })
    if (res.ok) {
      setNewName('')
      setNewSeat('')
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

      {/* 花名册 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">花名册 · 排除统计</CardTitle>
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
            <Button variant="outline" size="sm" onClick={addStudent}>
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
                  <TableHead>性别</TableHead>
                  <TableHead className="text-right">记录数</TableHead>
                  <TableHead className="text-center">排除统计</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {roster.map((row) => (
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
        </CardContent>
      </Card>
    </div>
  )
}
