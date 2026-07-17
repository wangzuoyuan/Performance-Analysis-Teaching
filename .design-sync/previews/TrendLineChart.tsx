import { TrendLineChart } from 'exam-tracker-frontend';

const wrap = { width: 460, maxWidth: '100%' } as const;

const scores = [
  { exam_name: '月考一', score: 72 },
  { exam_name: '期中', score: 78 },
  { exam_name: '月考二', score: 81 },
  { exam_name: '期末', score: 88 },
];

export function ScoreTrend() {
  return (
    <div style={wrap}>
      <TrendLineChart data={scores} yDataKey="score" color="#2563eb" />
    </div>
  );
}

const ranks = [
  { exam_name: '月考一', rank: 24 },
  { exam_name: '期中', rank: 15 },
  { exam_name: '月考二', rank: 12 },
  { exam_name: '期末', rank: 6 },
];

export function RankTrend() {
  return (
    <div style={wrap}>
      <TrendLineChart data={ranks} yDataKey="rank" color="#059669" invertY />
    </div>
  );
}
