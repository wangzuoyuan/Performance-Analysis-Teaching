'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useRef, useState } from 'react'
import {
  LayoutDashboard,
  Upload,
  BarChart3,
  ClipboardList,
  Users,
  NotebookPen,
  GraduationCap,
  School,
  Pencil,
  Check,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useClassScope } from '@/lib/class-scope'
import { currentScopeLabel } from '@/components/ClassScopePicker'

export interface TeacherSummary {
  name?: string | null
}

interface NavItem {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  match: (pathname: string) => boolean
}

const NAV_ITEMS: NavItem[] = [
  {
    href: '/',
    label: '仪表盘',
    icon: LayoutDashboard,
    match: (p) => p === '/',
  },
  {
    href: '/upload',
    label: '数据上传',
    icon: Upload,
    match: (p) => p.startsWith('/upload'),
  },
  {
    href: '/compare',
    label: '班级对比',
    icon: BarChart3,
    match: (p) => p.startsWith('/compare'),
  },
  {
    href: '/exam',
    label: '考试列表',
    icon: ClipboardList,
    match: (p) => p.startsWith('/exam'),
  },
  {
    href: '/student',
    label: '学生检索',
    icon: Users,
    match: (p) => p.startsWith('/student'),
  },
  {
    href: '/homework',
    label: '作业跟踪',
    icon: NotebookPen,
    match: (p) => p.startsWith('/homework'),
  },
  {
    href: '/settings/classes',
    label: '班级配置',
    icon: School,
    match: (p) => p.startsWith('/settings/classes'),
  },
]

interface SidebarContentProps {
  teacher: TeacherSummary | null
  onNameChange?: (name: string) => void
}

export function SidebarContent({ teacher, onNameChange }: SidebarContentProps) {
  const pathname = usePathname() || '/'
  const { classes, current } = useClassScope()

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  function startEdit() {
    setDraft(teacher?.name ?? '')
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  async function commitEdit() {
    const name = draft.trim()
    setEditing(false)
    try {
      const res = await fetch('/api/teacher', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (res.ok) onNameChange?.(name)
    } catch {
      // silent
    }
  }

  function cancelEdit() {
    setEditing(false)
  }

  return (
    <div className="flex h-full flex-col bg-slate-900 text-slate-100">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-slate-800 px-5">
        <GraduationCap className="h-6 w-6 text-brand-500" />
        <span className="text-lg font-semibold tracking-tight">成绩追踪</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const active = item.match(pathname)
          const Icon = item.icon
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-slate-800 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800/50'
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Footer card */}
      <div className="border-t border-slate-800 p-3">
        <div className="rounded-md bg-slate-800/60 px-3 py-3">
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-500">班主任</div>
            {!editing && (
              <button
                onClick={startEdit}
                className="text-slate-600 hover:text-slate-300 transition-colors"
                aria-label="编辑姓名"
              >
                <Pencil className="h-3 w-3" />
              </button>
            )}
          </div>
          {editing ? (
            <div className="mt-1 flex items-center gap-1">
              <input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitEdit()
                  if (e.key === 'Escape') cancelEdit()
                }}
                className="w-full rounded bg-slate-700 px-1.5 py-0.5 text-sm text-slate-100 outline-none focus:ring-1 focus:ring-brand-500"
                placeholder="输入姓名"
                maxLength={20}
              />
              <button onClick={commitEdit} className="text-success-500 hover:text-green-300">
                <Check className="h-3.5 w-3.5" />
              </button>
              <button onClick={cancelEdit} className="text-slate-500 hover:text-slate-300">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="mt-0.5 text-sm font-medium text-slate-100">
              {teacher?.name || '—'}
            </div>
          )}
          <div className="mt-2 flex items-center justify-between">
            <div className="text-xs text-slate-500">当前班级</div>
            <Link href="/settings/classes" className="text-xs text-brand-400 hover:text-brand-300">
              管理
            </Link>
          </div>
          <div className="mt-0.5 text-sm font-medium text-slate-100">
            {currentScopeLabel(current, classes)}
          </div>
        </div>
      </div>
    </div>
  )
}

interface SidebarProps {
  teacher: TeacherSummary | null
  onNameChange?: (name: string) => void
}

export function Sidebar({ teacher, onNameChange }: SidebarProps) {
  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:fixed md:inset-y-0 md:left-0 md:z-30 print:hidden">
      <SidebarContent teacher={teacher} onNameChange={onNameChange} />
    </aside>
  )
}
