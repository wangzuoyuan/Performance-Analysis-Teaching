import { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent, Button } from 'exam-tracker-frontend';

export function Hint() {
  return (
    <TooltipProvider>
      <div style={{ display: 'flex', gap: 40, padding: '48px 24px', justifyContent: 'center' }}>
        <Tooltip open>
          <TooltipTrigger asChild>
            <Button variant="outline" size="sm">临界生</Button>
          </TooltipTrigger>
          <TooltipContent>距上一段位不足 5 分的学生</TooltipContent>
        </Tooltip>
      </div>
    </TooltipProvider>
  );
}
