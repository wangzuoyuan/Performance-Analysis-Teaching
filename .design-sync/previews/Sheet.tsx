import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, Button, Badge } from 'exam-tracker-frontend';

export function StudentDrawer() {
  return (
    <Sheet open modal={false}>
      <SheetContent side="right" onInteractOutside={(e) => e.preventDefault()} onEscapeKeyDown={(e) => e.preventDefault()}>
        <SheetHeader>
          <SheetTitle>张伟 · 高二(3)班</SheetTitle>
          <SheetDescription>物理学科画像</SheetDescription>
        </SheetHeader>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 16 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <Badge variant="success">年级第 1</Badge>
            <Badge variant="secondary">选考物理</Badge>
          </div>
          <div style={{ fontSize: 14, color: '#475569', lineHeight: 1.6 }}>
            近三次考试稳定在 A 段，作业提交率 100%。建议冲刺培优。
          </div>
          <Button size="sm">导出家长会一页纸</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
