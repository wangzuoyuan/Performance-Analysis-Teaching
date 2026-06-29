'use client'

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

interface TrendLineChartProps {
  data: { exam_name: string; rank?: number; score?: number }[]
  yDataKey: string
  color?: string
  yDomain?: [number, number]
  invertY?: boolean
}

export default function TrendLineChart({
  data,
  yDataKey,
  color = '#2563eb',
  yDomain,
  invertY = false,
}: TrendLineChartProps) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
        <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="exam_name"
          tick={{ fontSize: 12, fill: '#64748b' }}
          stroke="#e2e8f0"
        />
        <YAxis
          domain={yDomain || [0, 'auto']}
          reversed={invertY}
          tick={{ fontSize: 12, fill: '#64748b' }}
          stroke="#e2e8f0"
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            boxShadow: '0 1px 2px 0 rgb(0 0 0 / 0.05)',
            fontSize: 12,
          }}
          labelStyle={{ color: '#0f172a', fontWeight: 500 }}
          itemStyle={{ color: '#334155' }}
        />
        <Line
          type="monotone"
          dataKey={yDataKey}
          stroke={color}
          strokeWidth={2}
          dot={{ r: 4, fill: color, strokeWidth: 0 }}
          activeDot={{ r: 6, fill: color, strokeWidth: 2, stroke: '#ffffff' }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
