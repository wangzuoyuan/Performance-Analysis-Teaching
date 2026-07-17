import { Avatar, AvatarImage, AvatarFallback } from 'exam-tracker-frontend';

const row = { display: 'flex', gap: 12, alignItems: 'center' } as const;

export function Fallbacks() {
  return (
    <div style={row}>
      <Avatar><AvatarFallback>张</AvatarFallback></Avatar>
      <Avatar><AvatarFallback>李</AvatarFallback></Avatar>
      <Avatar><AvatarFallback>王</AvatarFallback></Avatar>
      <Avatar><AvatarFallback>陈</AvatarFallback></Avatar>
    </div>
  );
}

export function WithImage() {
  return (
    <div style={row}>
      <Avatar>
        <AvatarImage src="https://i.pravatar.cc/80?img=12" alt="学生头像" />
        <AvatarFallback>生</AvatarFallback>
      </Avatar>
      <Avatar>
        <AvatarImage src="/broken.png" alt="加载失败回退" />
        <AvatarFallback>周</AvatarFallback>
      </Avatar>
    </div>
  );
}
