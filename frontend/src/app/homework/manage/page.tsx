'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { ChevronLeft, Trash2 } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface ManageRecord {
  id: number
  name: string
  date: string
  subject: string
  content: string
  remark: string
  is_special: boolean
}

export default function HomeworkManagePage() {
  const [records, setRecords] = useState<ManageRecord[]>([])
  const [student, setStudent] = useState('')
  const [date, setDate] = useState('')
  const [subject, setSubject] = useState('')
  const [loading, setLoading] = useState(false)
  // 先把 URL 上的 date/student/subject 读进来再触发加载，避免「无筛选请求」
  // 与「带筛选请求」竞争、前者后到把结果覆盖成全量。
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    setDate(params.get('date') || '')
    setStudent(params.get('student') || '')
    setSubject(params.get('subject') || '')
    setReady(true)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (student) params.set('student', student)
    if (date) params.set('date', date)
    if (subject) params.set('subject', subject)
    try {
      const data = await fetch(`/api/homework/manage/records?${params}`).then((r) => r.json())
      setRecords(data)
    } finally {
      setLoading(false)
    }
  }, [student, date, subject])

  useEffect(() => {
    if (ready) load().catch(() => {})
  }, [ready, load])

  async function remove(rec: ManageRecord) {
    if (!confirm(`删除 ${rec.name} 的这条记录？`)) return
    const url = rec.is_special
      ? `/api/homework/special-records/${rec.id}`
      : `/api/homework/manage/records/${rec.id}`
    await fetch(url, { method: 'DELETE' })
    await load()
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

      <Card>
        <CardHeader>
          <CardTitle className="text-base">记录管理</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={student}
              onChange={(e) => setStudent(e.target.value)}
              placeholder="按姓名筛选"
              className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            />
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="rounded-md border border-slate-200 px-2 py-1 text-sm"
            />
            {subject && (
              <Badge className="border-transparent bg-brand-50 text-brand-700">
                学科：{subject}
              </Badge>
            )}
            <Button variant="outline" size="sm" onClick={() => load()}>
              查询
            </Button>
            {(student || date || subject) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setStudent('')
                  setDate('')
                  setSubject('')
                }}
              >
                清空
              </Button>
            )}
          </div>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>日期</TableHead>
                  <TableHead>姓名</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>科目 / 情况</TableHead>
                  <TableHead>说明</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {records.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center text-sm text-slate-400">
                      {loading ? '加载中…' : '暂无记录'}
                    </TableCell>
                  </TableRow>
                ) : (
                  records.map((rec) => (
                    <TableRow key={`${rec.is_special ? 's' : 'r'}-${rec.id}`} className="hover:bg-slate-50">
                      <TableCell className="text-slate-500">{rec.date}</TableCell>
                      <TableCell className="font-medium">{rec.name}</TableCell>
                      <TableCell>
                        {rec.is_special ? (
                          <Badge className="border-transparent bg-warning-50 text-warning-700">特殊</Badge>
                        ) : (
                          <Badge className="border-transparent bg-slate-100 text-slate-600">缺交</Badge>
                        )}
                      </TableCell>
                      <TableCell>{rec.is_special ? rec.remark : rec.subject}</TableCell>
                      <TableCell className="text-slate-500">{rec.content || rec.remark || '—'}</TableCell>
                      <TableCell className="text-right">
                        <button
                          onClick={() => remove(rec)}
                          className="text-slate-400 hover:text-danger-500"
                          aria-label="删除"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
