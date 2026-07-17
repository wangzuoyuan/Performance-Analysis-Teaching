import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableCaption, Badge } from 'exam-tracker-frontend';

const rows = [
  { no: 1, name: '张伟', score: 96, rank: 1, tag: '优秀' },
  { no: 2, name: '李娜', score: 89, rank: 3, tag: '优秀' },
  { no: 3, name: '王强', score: 72, rank: 18, tag: '临界' },
  { no: 4, name: '陈静', score: 58, rank: 34, tag: '薄弱' },
];

export function ScoreTable() {
  return (
    <Table>
      <TableCaption>高二(3)班 物理 · 期中成绩</TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>座号</TableHead>
          <TableHead>姓名</TableHead>
          <TableHead>分数</TableHead>
          <TableHead>年级排名</TableHead>
          <TableHead>标签</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.no}>
            <TableCell>{r.no}</TableCell>
            <TableCell style={{ fontWeight: 600 }}>{r.name}</TableCell>
            <TableCell>{r.score}</TableCell>
            <TableCell>{r.rank}</TableCell>
            <TableCell>
              <Badge variant={r.tag === '优秀' ? 'success' : r.tag === '临界' ? 'warning' : 'destructive'}>{r.tag}</Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
