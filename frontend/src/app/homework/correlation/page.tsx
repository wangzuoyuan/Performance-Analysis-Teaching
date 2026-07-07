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
export default function CorrelationPage() {
  const [data, setData] = useState<Correlation | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      // 不传 class_num：后端按全花名册（我教的所有班并集）统计
      const corr = await fetch('/api/homework/correlation').then((r) => r.json())
      setData(corr)
    } catch {
      setError('加载失败')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

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
          <CardTitle className="text-base">缺交总数 × 学籍排名</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <p className="py-10 text-center text-sm text-slate-400">{error}</p>
          ) : points.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-400">
              暂无可对照数据（需该班已导入考试成绩）
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
                红点 = 缺交偏多且排名靠后的学生，落在重点关注象限。
                {yField === 'grade_percentile' ? '年级百分位越小越靠前（图中越高）。' : '学籍排名越小越靠前（图中越高）。'}
                作业数据仅反映缺交，不代表完成质量。
              </p>
            </>
          )}
        </CardContent>
      </Card>

      {flagged.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              重点关注（高缺交 + 排名靠后）
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
