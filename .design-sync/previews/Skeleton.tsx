import { Skeleton } from 'exam-tracker-frontend';

export function CardLoading() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 340, padding: 16, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Skeleton style={{ height: 44, width: 44, borderRadius: 9999 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
          <Skeleton style={{ height: 14, width: '60%' }} />
          <Skeleton style={{ height: 12, width: '40%' }} />
        </div>
      </div>
      <Skeleton style={{ height: 12, width: '100%' }} />
      <Skeleton style={{ height: 12, width: '90%' }} />
      <Skeleton style={{ height: 12, width: '75%' }} />
    </div>
  );
}

export function ListLoading() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 320 }}>
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} style={{ height: 40, width: '100%', borderRadius: 8 }} />
      ))}
    </div>
  );
}
