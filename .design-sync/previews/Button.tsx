import { Button } from 'exam-tracker-frontend';

const row = { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' } as const;

export function Variants() {
  return (
    <div style={row}>
      <Button>保存成绩</Button>
      <Button variant="secondary">取消</Button>
      <Button variant="outline">导出 Excel</Button>
      <Button variant="destructive">删除考试</Button>
      <Button variant="ghost">更多</Button>
      <Button variant="link">查看详情</Button>
    </div>
  );
}

export function Sizes() {
  return (
    <div style={row}>
      <Button size="sm">小号</Button>
      <Button size="default">默认</Button>
      <Button size="lg">大号按钮</Button>
    </div>
  );
}

export function Disabled() {
  return (
    <div style={row}>
      <Button disabled>提交中…</Button>
      <Button variant="outline" disabled>不可用</Button>
    </div>
  );
}
