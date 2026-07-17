import { Badge } from 'exam-tracker-frontend';

const row = { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' } as const;

export function Variants() {
  return (
    <div style={row}>
      <Badge>物理</Badge>
      <Badge variant="secondary">高二(3)班</Badge>
      <Badge variant="success">已提交</Badge>
      <Badge variant="warning">临界生</Badge>
      <Badge variant="destructive">连续缺交</Badge>
      <Badge variant="outline">选考</Badge>
    </div>
  );
}

export function StatusTags() {
  return (
    <div style={row}>
      <Badge variant="success">进步 +12 名</Badge>
      <Badge variant="warning">下滑 3 名</Badge>
      <Badge variant="destructive">薄弱学科</Badge>
    </div>
  );
}
