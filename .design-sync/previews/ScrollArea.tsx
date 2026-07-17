import { ScrollArea, Separator } from 'exam-tracker-frontend';

const students = ['张伟', '李娜', '王强', '陈静', '刘洋', '赵敏', '孙磊', '周涛', '吴婷', '郑浩', '冯雪', '蒋波'];

export function StudentList() {
  return (
    <ScrollArea style={{ height: 200, width: 260, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ padding: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 8 }}>高二(3)班 花名册</div>
        {students.map((s, i) => (
          <div key={s}>
            <div style={{ padding: '8px 4px', fontSize: 14, color: '#475569' }}>{i + 1}. {s}</div>
            {i < students.length - 1 && <Separator />}
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
