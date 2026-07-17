import { Tabs, TabsList, TabsTrigger, TabsContent } from 'exam-tracker-frontend';

const panel = { padding: 16, fontSize: 14, color: '#475569', lineHeight: 1.6 } as const;

export function AnalysisTabs() {
  return (
    <Tabs defaultValue="overview" style={{ maxWidth: 420 }}>
      <TabsList>
        <TabsTrigger value="overview">总览</TabsTrigger>
        <TabsTrigger value="bands">段位分布</TabsTrigger>
        <TabsTrigger value="homework">作业</TabsTrigger>
      </TabsList>
      <TabsContent value="overview">
        <div style={panel}>平均分 78.4，及格率 82%，较上次进步 3.2 分。全班共 42 人参加考试。</div>
      </TabsContent>
      <TabsContent value="bands">
        <div style={panel}>A 段 8 人 · B 段 19 人 · C 段 11 人 · D 段 4 人。</div>
      </TabsContent>
      <TabsContent value="homework">
        <div style={panel}>本周作业提交率 92%，2 名学生连续缺交，已进入预警名单。</div>
      </TabsContent>
    </Tabs>
  );
}
