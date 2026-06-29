'use client'

import { useEffect, useState } from 'react'
import { NotebookPen } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface WarnItem {
  name: string
  subject: string
  streak: number
  dates: string[]
}
interface RecentRecord {
  date: string
  subject: string
  content: string
}
interface HomeworkSummary {
  student?: { student_id: string; name: string; excluded: boolean }
  total_misses?: number
  miss_by_subject?: Record<string, number>
  special_counts?: Record<string, number>
  active_warnings?: WarnItem[]
  recent_records?: RecentRecord[]
  error?: string
}

export default function HomeworkCard({ studentId }: { studentId: string }) {
  const [data, setData] = useState<HomeworkSummary | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!studentId) return
    fetch(`/api/homework/student/${studentId}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData({ error: '加载失败' }))
      .finally(() => setLoaded(true))
  }, [studentId])

  // 该生不在作业花名册（如非6班）时不显示卡片
  if (loaded && (!data || data.error)) return null

  const subjects = Object.entries(data?.miss_by_subject || {})
  const specials = Object.entries(data?.special_counts || {})
  const warnings = data?.active_warnings || []
  const recent = data?.recent_records || []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <NotebookPen className="h-4 w-4" />
          本学期作业缺交
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <div>
            <span className="text-3xl font-semibold text-slate-900">
              {data?.total_misses ?? '—'}
            </span>
            <span className="ml-1 text-sm text-slate-500">次缺交</span>
          </div>
          {specials.length > 0 && (
            <div className="text-sm text-slate-500">
              {specials.map(([t, c]) => `${t} ${c} 次`).join(' · ')}
            </div>
          )}
          {data?.student?.excluded && (
            <Badge className="border-transparent bg-slate-100 text-slate-500">不计入统计</Badge>
          )}
        </div>

        {subjects.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {subjects.map(([sub, count]) => (
              <span
                key={sub}
                className="rounded-md bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
              >
                {sub} <span className="font-medium text-slate-800">{count}</span>
              </span>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">本学期暂无缺交记录</p>
        )}

        {warnings.length > 0 && (
          <div className="space-y-1.5 border-t border-slate-100 pt-3">
            <div className="text-xs font-medium text-slate-500">连续缺交预警</div>
            {warnings.map((w, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <Badge
                  className={
                    w.streak >= 3
                      ? 'border-transparent bg-danger-50 text-danger-600'
                      : 'border-transparent bg-warning-50 text-warning-700'
                  }
                >
                  连续{w.streak}次
                </Badge>
                <span className="text-slate-600">{w.subject}</span>
                <span className="text-xs text-slate-400">
                  {w.dates[0]?.slice(5)} ~ {w.dates[w.dates.length - 1]?.slice(5)}
                </span>
              </div>
            ))}
          </div>
        )}

        {recent.length > 0 && (
          <details className="border-t border-slate-100 pt-3" open>
            <summary className="cursor-pointer text-xs font-medium text-slate-500">
              近期缺交明细（{recent.length} 条）
            </summary>
            <table className="mt-2 w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400">
                  <th className="py-1 font-normal">日期</th>
                  <th className="py-1 font-normal">学科</th>
                  <th className="py-1 font-normal">说明</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r, i) => (
                  <tr key={i} className="border-t border-slate-50">
                    <td className="py-1.5 text-slate-500">{r.date}</td>
                    <td className="py-1.5 text-slate-700">{r.subject}</td>
                    <td className="py-1.5 text-slate-500">{r.content || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}

        <p className="text-xs text-slate-400">
          仅含缺交、请假、迟到等记录，不代表作业完成质量。
        </p>
      </CardContent>
    </Card>
  )
}
