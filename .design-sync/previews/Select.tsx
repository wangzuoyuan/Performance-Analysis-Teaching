import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem, SelectGroup, SelectLabel } from 'exam-tracker-frontend';

const wrap = { maxWidth: 240 } as const;

export function ClassPicker() {
  return (
    <div style={wrap}>
      <Select defaultValue="g2c3">
        <SelectTrigger>
          <SelectValue placeholder="选择教学班" />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>高二物理</SelectLabel>
            <SelectItem value="g2c3">高二(3)班</SelectItem>
            <SelectItem value="g2c5">高二(5)班</SelectItem>
            <SelectItem value="wA1">物 A1 走班</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  );
}

export function ExamPicker() {
  return (
    <div style={wrap}>
      <Select>
        <SelectTrigger>
          <SelectValue placeholder="选择考试" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="mid">期中考试</SelectItem>
          <SelectItem value="final">期末考试</SelectItem>
          <SelectItem value="month">月考</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
