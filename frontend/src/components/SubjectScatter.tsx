'use client'

import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from 'recharts'

interface SubjectScatterProps {
  data: { subject: string; x: number; y: number; name: string }[]
  xKey: string
  yKey: string
}

// 散点统一用 brand-500，参考线用 slate-300，颜色 token 化
const POINT_COLOR = '#3b82f6' // brand-500
const REF_COLOR = '#cbd5e1'   // slate-300

export default function SubjectScatter({ data, xKey, yKey }: SubjectScatterProps) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ScatterChart margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
        <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
        <XAxis
          dataKey={xKey}
          name="主三门百分位"
          tick={{ fontSize: 12, fill: '#64748b' }}
          stroke="#e2e8f0"
        />
        <YAxis
          dataKey={yKey}
          name="单科百分位"
          tick={{ fontSize: 12, fill: '#64748b' }}
          stroke="#e2e8f0"
        />
        <Tooltip
          cursor={{ strokeDasharray: '3 3', stroke: '#cbd5e1' }}
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
        {/* 对角参考线：x = y，便于看偏科 */}
        <ReferenceLine
          segment={[
            { x: 0, y: 0 },
            { x: 1, y: 1 },
          ]}
          stroke={REF_COLOR}
          strokeDasharray="4 4"
        />
        <Scatter data={data}>
          {data.map((_, i) => (
            <Cell key={i} fill={POINT_COLOR} />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  )
}
