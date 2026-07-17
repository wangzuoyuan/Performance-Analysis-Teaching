import { RankBandStackedBar } from 'exam-tracker-frontend';

const data = [
  { class_num: 1, high_score: 9, critical: 6, weak: 3 },
  { class_num: 3, high_score: 8, critical: 5, weak: 4 },
  { class_num: 5, high_score: 6, critical: 7, weak: 5 },
  { class_num: 7, high_score: 5, critical: 8, weak: 6 },
];

export function BandsByClass() {
  return (
    <div style={{ width: 460, maxWidth: '100%' }}>
      <RankBandStackedBar
        data={data}
        labels={{ high_score: '优秀', critical: '临界', weak: '薄弱' }}
      />
    </div>
  );
}
