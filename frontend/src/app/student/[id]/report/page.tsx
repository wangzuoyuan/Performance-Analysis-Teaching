'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ChevronLeft, Printer } from 'lucide-react'

import { useClassScope } from '@/lib/class-scope'

const DASH = '—'

interface ScoreTrendPoint {
  exam_name: string
  exam_date?: string | null
  subject: string
  raw_score?: number | null
  grade_score?: number | null
  grade_percentile?: number | null
  scope_rank?: number | null
}
interface StudentProfile {
  student_id: string
  name: string
  class_label?: string | null
  teaching_subject?: string | null
  score_trend: ScoreTrendPoint[]
}
interface HomeworkSummary {
  total_misses?: number
  miss_by_subject?: Record<string, number>
  special_counts?: Record<string, number>
  error?: string
}
interface Note {
  id: number
  date: string
  category: string
  content: string
}

function num(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  return null
}

export default function StudentReportPage() {
  const params = useParams<{ id: string }>()
  const studentId = Array.isArray(params?.id) ? params?.id[0] : params?.id
  const { scopeParam } = useClassScope()
  const tcId = scopeParam().teaching_class_id

  const [profile, setProfile] = useState<StudentProfile | null>(null)
  const [homework, setHomework] = useState<HomeworkSummary | null>(null)
  const [notes, setNotes] = useState<Note[]>([])

  useEffect(() => {
    if (!studentId) return
    const sp = new URLSearchParams()
    if (tcId != null) sp.set('teaching_class_id', String(tcId))
    const qs = sp.toString()
    fetch(`/api/students/${studentId}${qs ? `?${qs}` : ''}`).then((r) => r.json()).then(setProfile).catch(() => {})
    fetch(`/api/homework/student/${studentId}`).then((r) => r.json()).then(setHomework).catch(() => {})
    fetch(`/api/notes/${studentId}`).then((r) => r.json()).then((d) => setNotes(Array.isArray(d) ? d : [])).catch(() => {})
  }, [studentId, tcId])

  if (!profile) {
    return <div className="p-8 text-sm text-slate-400">加载中…</div>
  }

  const subject = profile.teaching_subject ?? null
  const trend = [...(profile.score_trend || [])].sort((a, b) =>
    (a.exam_date ?? '') < (b.exam_date ?? '') ? -1 : 1
  )
  const latest = trend[trend.length - 1]
  const first = trend[0]

  const hwSubjects = Object.entries(homework?.miss_by_subject || {})
  const hwSpecials = Object.entries(homework?.special_counts || {})

  return (
    <div className="mx-auto max-w-3xl space-y-5 bg-white p-6 text-slate-900 print:p-0">
      {/* 顶部操作（打印时隐藏） */}
      <div className="flex items-center justify-between print:hidden">
        <Link
          href={`/student/${studentId}`}
          className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"
        >
          <ChevronLeft className="h-4 w-4" />
          返回学生页
        </Link>
        <button
          onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 rounded-md bg-brand-600 px-3 py-1.5 text-sm text-white hover:bg-brand-700"
        >
          <Printer className="h-4 w-4" />
          打印 / 存为 PDF
        </button>
      </div>

      {/* 抬头 */}
      <div className="border-b border-slate-300 pb-3">
        <h1 className="text-xl font-bold">家长会学生情况表</h1>
        <p className="mt-1 text-sm text-slate-600">
          {profile.name} · 学号 {profile.student_id}
          {profile.class_label ? ` · ${profile.class_label}` : ''}
          {subject ? ` · ${subject}` : ''}
          <span className="ml-3 text-slate-400">生成日期 {new Date().toISOString().slice(0, 10)}</span>
        </p>
      </div>

      {/* 成绩概况：当前学科历次 */}
      <section>
        <h2 className="mb-2 text-base font-semibold">
          一、{subject ?? '学科'}成绩概况
        </h2>
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="py-1.5 font-normal">考试</th>
              <th className="py-1.5 font-normal text-right">原始分</th>
              <th className="py-1.5 font-normal text-right">等级分</th>
              <th className="py-1.5 font-normal text-right">百分位</th>
              <th className="py-1.5 font-normal text-right">教学班排名</th>
            </tr>
          </thead>
          <tbody>
            {trend.map((p, i) => (
              <tr key={i} className="border-b border-slate-100">
                <td className="py-1.5">{p.exam_name}</td>
                <td className="py-1.5 text-right tabular-nums">{num(p.raw_score) ?? DASH}</td>
                <td className="py-1.5 text-right tabular-nums">{num(p.grade_score) ?? DASH}</td>
                <td className="py-1.5 text-right tabular-nums">
                  {num(p.grade_percentile) !== null ? `${Math.round(num(p.grade_percentile)! * 100)}%` : DASH}
                </td>
                <td className="py-1.5 text-right tabular-nums">{num(p.scope_rank) ?? DASH}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {latest && first && num(latest.scope_rank) !== null && num(first.scope_rank) !== null && (
          <p className="mt-2 text-sm text-slate-600">
            教学班排名从 {num(first.scope_rank)} 变化到 {num(latest.scope_rank)}
            （{(num(first.scope_rank)! - num(latest.scope_rank)!) >= 0 ? '前进' : '后退'}{' '}
            {Math.abs(num(first.scope_rank)! - num(latest.scope_rank)!)} 名）。
          </p>
        )}
      </section>

      {/* 作业 */}
      <section>
        <h2 className="mb-2 text-base font-semibold">二、作业完成情况（本学期缺交）</h2>
        {homework && !homework.error ? (
          <p className="text-sm text-slate-700">
            共缺交 <span className="font-semibold">{homework.total_misses ?? 0}</span> 次
            {hwSpecials.length > 0 && `；${hwSpecials.map(([t, c]) => `${t}${c}次`).join('、')}`}
            {hwSubjects.length > 0 && (
              <span className="text-slate-500">
                （{hwSubjects.map(([s, c]) => `${s}${c}`).join('、')}）
              </span>
            )}
            。<span className="text-slate-400">注：仅含缺交/请假/迟到，不代表完成质量。</span>
          </p>
        ) : (
          <p className="text-sm text-slate-400">无作业记录</p>
        )}
      </section>

      {/* 谈话摘要 */}
      <section>
        <h2 className="mb-2 text-base font-semibold">三、近期沟通摘要</h2>
        {notes.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {notes.slice(0, 4).map((n) => (
              <li key={n.id} className="text-slate-700">
                <span className="text-slate-400">{n.date}</span>{' '}
                <span className="font-medium">[{n.category}]</span> {n.content}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">暂无记录</p>
        )}
      </section>

      <div className="border-t border-slate-300 pt-3 text-xs text-slate-400 print:fixed print:bottom-2">
        本表由成绩追踪系统生成，仅供家校沟通参考。
      </div>
    </div>
  )
}
