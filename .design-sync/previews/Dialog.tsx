import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Button } from 'exam-tracker-frontend';

export function ConfirmDelete() {
  return (
    <Dialog open modal={false}>
      <DialogContent onEscapeKeyDown={(e) => e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>删除这场考试？</DialogTitle>
          <DialogDescription>
            将级联删除「高二物理期中考试」的所有成绩、段位与班级均分数据，且不可恢复。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="outline">取消</Button>
          <Button variant="destructive">确认删除</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
