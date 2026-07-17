import { Input } from 'exam-tracker-frontend';

const col = { display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 320 } as const;
const label = { fontSize: 13, fontWeight: 600, color: '#334155', marginBottom: 4 } as const;

export function Default() {
  return (
    <div style={col}>
      <div>
        <div style={label}>学生姓名</div>
        <Input placeholder="请输入姓名，如 张三" />
      </div>
      <div>
        <div style={label}>搜索学号</div>
        <Input type="search" placeholder="按学号或姓名筛选…" />
      </div>
    </div>
  );
}

export function States() {
  return (
    <div style={col}>
      <Input defaultValue="高二物理期中考试" />
      <Input disabled placeholder="锁定字段（不可编辑）" />
    </div>
  );
}
