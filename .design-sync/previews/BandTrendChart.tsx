import { BandTrendChart } from 'exam-tracker-frontend';

const data = [
  { exam_id: 1, exam_name: '月考一', high_score: 6, critical: 8, weak: 7 },
  { exam_id: 2, exam_name: '期中', high_score: 8, critical: 7, weak: 5 },
  { exam_id: 3, exam_name: '月考二', high_score: 9, critical: 6, weak: 4 },
  { exam_id: 4, exam_name: '期末', high_score: 11, critical: 5, weak: 3 },
];

export function BandsOverTime() {
  return (
    <div style={{ width: 460, maxWidth: '100%' }}>
      <BandTrendChart
        data={data}
        labels={{ high_score: '优秀', critical: '临界', weak: '薄弱' }}
      />
    </div>
  );
}
