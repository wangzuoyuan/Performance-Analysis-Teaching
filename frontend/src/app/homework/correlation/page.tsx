'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { ChevronLeft } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

const SUBJECTS = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理']

interface Row {
  student_id: string
  name: string
  miss_count: number
  xueji_rank?: number | null
  grade_percentile?: number | null
}
interface Correlation {
  exam_id: number | null
  subject: string | null
  y_field: string
  y_label: string
  rows: Row[]
}
interface SubjectRank {
  subject: string
  r: number | null
  n: number
}

export default function CorrelationPage() {
  const [subject, setSubject] = useState('') // '' = 总览
  const [data, setData] = useState<Correlation | null>(null)
  const [ranking, setRanking] = useState<SubjectRank[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (sub: string) => {
    setError(null)
    try {
      const q = `class_num=6${sub ? `&subject=${encodeURIComponent(sub)}` : ''}`
      const corr = await fetch(`/api/homework/correlation?${q}`).then((r) => r.json())
      setData(corr)
      if (!sub) {
        const rk = await fetch('/api/homework/correlation/subjects?class_num=6').then((r) => r.json())
        setRanking(rk.rankings || [])
      }
    } catch {
      setError('加载失败')
    }
  }, [])

  useEffect(() => {
    load(subject)
  }, [subject, load])

  const yField: 'xueji_rank' | 'grade_percentile' =
    data?.y_field === 'grade_percentile' ? 'grade_percentile' : 'xueji_rank'

  const points = useMemo(
    () =>
      (data?.rows || [])
        .filter((r) => r[yField] != null)
        .map((r) => ({ x: r.miss_count, y: r[yField] as number, name: r.name })),
    [data, yField]
  )

  const missThreshold = useMemo(() => {
    if (points.length === 0) return 0
    const xs = points.map((p) => p.x).sort((a, b) => a - b)
    return xs[Math.floor(xs.length * 0.7)]
  }, [points])
  const yThreshold = useMemo(() => {
    if (points.length === 0) return 0
    const ys = points.map((p) => p.y).sort((a, b) => a - b)
    return ys[Math.floor(ys.length * 0.6)]
  }, [points])
  const flagged = useMemo(
    () => points.filter((p) => p.x >= missThreshold && p.y >= yThreshold),
    [points, missThreshold, yThreshold]
  )
  const flaggedNames = new Set(flagged.map((p) => p.name))

  const yLabel = data?.y_label || '学籍排名'
  const maxAbsR = Math.max(0.0001, ...ranking.map((r) => Math.abs(r.r ?? 0)))

  return (
    <div className="space-y-6">
      <Link
        href="/homework"
        className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"
      >
        <ChevronLeft className="h-4 w-4" />
        返回作业看板
      </Link>

      {/* 学科选择器 */}
      <div className="flex flex-wrap gap-1.5">
        <button
          onClick={() => setSubject('')}
          className={cn(
            'rounded-md px-3 py-1.5 text-sm',
            subject === '' ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          )}
        >
          总览
        </button>
        {SUBJECTS.map((s) => (
          <button
            key={s}
            onClick={() => setSubject(s)}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm',
              subject === s ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            )}
          >
            {s}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {subject ? `${subject}：缺交 × 该科成绩` : '缺交总数 × 学籍排名'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="py-10 text-center text-sm text-slate-400">{error}</p>
          ) : points.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-400">
              暂无可对照数据{subject ? `（最近考试可能未考${subject}）` : '（需该班已导入考试成绩）'}
            </p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={420}>
                <ScatterChart margin={{ top: 16, right: 24, bottom: 32, left: 8 }}>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    name="缺交次数"
                    tick={{ fontSize: 11, fill: '#64748b' }}
                    stroke="#e2e8f0"
                    label={{ value: '缺交次数 →', position: 'insideBottom', offset: -16, fontSize: 12, fill: '#64748b' }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name={yLabel}
                    reversed
                    domain={yField === 'grade_percentile' ? [0, 1] : ['auto', 'auto']}
                    tick={{ fontSize: 11, fill: '#64748b' }}
                    stroke="#e2e8f0"
                    label={{ value: `${yLabel}（越上越好）`, angle: -90, position: 'insideLeft', fontSize: 12, fill: '#64748b' }}
                  />
                  <ZAxis range={[60, 60]} />
                  <RTooltip
                    cursor={{ strokeDasharray: '3 3' }}
                    content={({ payload }) => {
                      const p = payload?.[0]?.payload as { name: string; x: number; y: number } | undefined
                      if (!p) return null
                      const yText =
                        yField === 'grade_percentile' ? `${Math.round(p.y * 100)}%` : p.y
                      return (
                        <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-sm">
                          <div className="font-medium text-slate-800">{p.name}</div>
                          <div className="text-slate-500">
                            缺交 {p.x} 次 · {yLabel} {yText}
                          </div>
                        </div>
                      )
                    }}
                  />
                  <Scatter data={points}>
                    {points.map((p, i) => (
                      <Cell key={i} fill={flaggedNames.has(p.name) ? '#dc2626' : '#94a3b8'} />
                    ))}
                    <LabelList
                      dataKey="name"
                      position="top"
                      content={(props) => {
                        const { x, y, value } = props as { x?: number; y?: number; value?: string }
                        if (x == null || y == null || !value) return null
                        const flagged = flaggedNames.has(value)
                        return (
                          <text
                            x={x}
                            y={y - 6}
                            textAnchor="middle"
                            fontSize={10}
                            fill={flagged ? '#dc2626' : '#94a3b8'}
                            fontWeight={flagged ? 600 : 400}
                          >
                            {value}
                          </text>
                        )
                      }}
                    />
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
              <p className="mt-2 text-xs text-slate-400">
                红点 = 缺交偏多且{subject ? '该科成绩偏弱' : '排名靠后'}的学生，落在重点关注象限。
                {yField === 'grade_percentile' ? '年级百分位越小越靠前（图中越高）。' : '学籍排名越小越靠前（图中越高）。'}
                作业数据仅反映缺交，不代表完成质量。
              </p>
            </>
          )}
        </CardContent>
      </Card>

      {/* 总览模式：各科相关强弱 */}
      {!subject && ranking.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">各科「缺交拖成绩」相关强弱</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {ranking.map((r) => (
                <div key={r.subject} className="flex items-center gap-3">
                  <button
                    onClick={() => setSubject(r.subject)}
                    className="w-12 shrink-0 text-left text-sm font-medium text-brand-700 hover:underline"
                  >
                    {r.subject}
                  </button>
                  <div className="h-4 flex-1 rounded bg-slate-100">
                    {r.r != null && r.r > 0 && (
                      <div
                        className="h-4 rounded bg-danger-400"
                        style={{ width: `${(r.r / maxAbsR) * 100}%` }}
                      />
                    )}
                  </div>
                  <div className="w-28 shrink-0 text-right text-xs tabular-nums text-slate-500">
                    {r.r == null ? `样本不足(n=${r.n})` : `r=${r.r.toFixed(2)} · n=${r.n}`}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-slate-400">
              r 为皮尔逊相关系数，正值越大表示该科缺交越多、成绩越差（缺交越拖该科成绩）。点学科名查看该科散点。
            </p>
          </CardContent>
        </Card>
      )}

      {flagged.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              重点关注（高缺交 + {subject ? '该科偏弱' : '排名靠后'}）
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {flagged
                .sort((a, b) => b.x - a.x)
                .map((p) => (
                  <span key={p.name} className="rounded-md bg-danger-50 px-3 py-1.5 text-sm text-danger-600">
                    {p.name} · 缺交{p.x}次 ·{' '}
                    {yField === 'grade_percentile' ? `${Math.round(p.y * 100)}%` : `排名${p.y}`}
                  </span>
                ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
