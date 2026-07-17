import { AuthGate, Card, CardHeader, CardTitle, CardContent } from 'exam-tracker-frontend';

// When the auth-status request fails (as it does in an isolated preview),
// AuthGate falls through to rendering its children — so this card shows the
// gate in its pass-through state around real app content.
export function PassThrough() {
  return (
    <div style={{ maxWidth: 360 }}>
      <AuthGate>
        <Card>
          <CardHeader><CardTitle>受保护的内容</CardTitle></CardHeader>
          <CardContent style={{ fontSize: 14, color: '#475569' }}>
            通过鉴权后展示的页面内容。内网 / 本地开发环境自动放行。
          </CardContent>
        </Card>
      </AuthGate>
    </div>
  );
}
