import { Separator } from 'exam-tracker-frontend';

export function Horizontal() {
  return (
    <div style={{ maxWidth: 320 }}>
      <div style={{ fontWeight: 600, fontSize: 15 }}>高二(3)班 物理</div>
      <div style={{ fontSize: 13, color: '#64748b' }}>期中考试成绩分析</div>
      <Separator style={{ margin: '12px 0' }} />
      <div style={{ display: 'flex', gap: 16, fontSize: 13, color: '#475569' }}>
        <span>平均分 78.4</span>
        <span>最高 96</span>
        <span>及格率 82%</span>
      </div>
    </div>
  );
}

export function Vertical() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, height: 40, fontSize: 14, color: '#334155' }}>
      <span>年级排名 12</span>
      <Separator orientation="vertical" />
      <span>班级排名 2</span>
      <Separator orientation="vertical" />
      <span>较上次 +5</span>
    </div>
  );
}
