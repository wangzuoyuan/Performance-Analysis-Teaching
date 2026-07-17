import { ToolCallCard } from 'exam-tracker-frontend';

const wrap = { maxWidth: 460 } as const;

export function Success() {
  return (
    <div style={wrap}>
      <ToolCallCard
        collapsed={false}
        toolCall={{
          name: 'focus_list',
          input: { exam_id: 128, teaching_class_id: 3 },
          output: { critical: ['王强', '赵敏'], weak: ['陈静'] },
        }}
      />
    </div>
  );
}

export function ErrorState() {
  return (
    <div style={wrap}>
      <ToolCallCard
        toolCall={{
          name: 'student_trend',
          input: { student_id: '2023056' },
          error: '未找到该学号对应的成绩记录',
        }}
      />
    </div>
  );
}
