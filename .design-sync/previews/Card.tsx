import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter, Button, Badge } from 'exam-tracker-frontend';

export function StatCard() {
  return (
    <Card style={{ maxWidth: 340 }}>
      <CardHeader>
        <CardTitle>班级平均分</CardTitle>
        <CardDescription>高二(3)班 · 物理 · 期中考试</CardDescription>
      </CardHeader>
      <CardContent>
        <div style={{ fontSize: 34, fontWeight: 700, color: '#2563eb' }}>78.4</div>
        <div style={{ fontSize: 13, color: '#16a34a', marginTop: 4 }}>较上次 +3.2 分</div>
      </CardContent>
      <CardFooter>
        <Badge variant="success">年级第 2</Badge>
      </CardFooter>
    </Card>
  );
}

export function ActionCard() {
  return (
    <Card style={{ maxWidth: 360 }}>
      <CardHeader>
        <CardTitle>数据备份</CardTitle>
        <CardDescription>上次备份：3 天前</CardDescription>
      </CardHeader>
      <CardContent style={{ fontSize: 14, color: '#475569' }}>
        备份包含成绩库与作业导出，可随时恢复到指定时间点。
      </CardContent>
      <CardFooter style={{ display: 'flex', gap: 8 }}>
        <Button size="sm">立即备份</Button>
        <Button size="sm" variant="outline">查看历史</Button>
      </CardFooter>
    </Card>
  );
}
