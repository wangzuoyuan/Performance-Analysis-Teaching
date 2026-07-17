import { SubjectScatter } from 'exam-tracker-frontend';

const data = [
  { subject: '物理', name: '张伟', x: 96, y: 2 },
  { subject: '物理', name: '李娜', x: 89, y: 8 },
  { subject: '物理', name: '王强', x: 72, y: 18 },
  { subject: '物理', name: '陈静', x: 58, y: 34 },
  { subject: '物理', name: '刘洋', x: 81, y: 11 },
  { subject: '物理', name: '赵敏', x: 65, y: 27 },
];

export function ScoreVsRank() {
  return (
    <div style={{ width: 460, maxWidth: '100%' }}>
      <SubjectScatter data={data} xKey="x" yKey="y" />
    </div>
  );
}
