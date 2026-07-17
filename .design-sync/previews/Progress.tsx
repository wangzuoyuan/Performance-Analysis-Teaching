import { Progress } from 'exam-tracker-frontend';

const col = { display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 360 } as const;
const cap = { fontSize: 13, color: '#475569', marginBottom: 6, display: 'flex', justifyContent: 'space-between' } as const;

export function SubmissionRates() {
  return (
    <div style={col}>
      <div>
        <div style={cap}><span>作业提交率</span><span>92%</span></div>
        <Progress value={92} />
      </div>
      <div>
        <div style={cap}><span>及格率</span><span>68%</span></div>
        <Progress value={68} />
      </div>
      <div>
        <div style={cap}><span>优秀率</span><span>34%</span></div>
        <Progress value={34} />
      </div>
    </div>
  );
}
