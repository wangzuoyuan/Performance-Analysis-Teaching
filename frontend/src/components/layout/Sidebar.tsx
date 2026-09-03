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
    <div className="flex h-full flex-col bg-[rgba(250,253,255,0.92)] text-[#46688c] backdrop-blur">
      {/* Logo */}
      <div className="relative flex items-center gap-2.5 border-b border-[#cbe2f5]/60 px-5 py-4">
        <span className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-[9px] bg-gradient-to-br from-[#1f7fd6] to-[#35b9e9] text-white shadow-[0_4px_12px_rgba(31,127,214,0.35),inset_0_1px_0_rgba(255,255,255,0.4)]">
          <GraduationCap className="h-5 w-5" />
        </span>
        <div>
          <div className="text-[15px] font-semibold tracking-wide text-[#16324a]">成绩追踪</div>
          <div className="mt-px text-[9px] uppercase tracking-[0.22em] text-[#9cc4e8]">
            Performance Analysis
          </div>
        </div>
        <span
          aria-hidden="true"
          className="absolute bottom-[-3px] left-5 right-5 h-px bg-gradient-to-r from-[#35b9e9] to-transparent opacity-70"
        />
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
                'flex items-center gap-3 rounded-lg border border-transparent px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-gradient-to-r from-[#1f7fd6]/95 to-[#35b9e9]/90 text-white shadow-[0_4px_12px_rgba(31,127,214,0.32),inset_0_1px_0_rgba(255,255,255,0.35)]'
                  : 'text-[#46688c] hover:bg-[#1f7fd6]/[0.07] hover:text-[#0e5fa8]'
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Footer card */}
      <div className="border-t border-[#cbe2f5]/60 p-3">
        <div className="rounded-[10px] border border-[#cbe2f5] bg-gradient-to-b from-white/90 to-[#eaf5fd]/70 px-3 py-3">
          <div className="flex items-center justify-between">
            <div className="text-xs text-[#58789b]">班主任</div>
            {!editing && (
              <button
                onClick={startEdit}
                className="text-[#8fb8dc] transition-colors hover:text-[#1f7fd6]"
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
                className="w-full rounded bg-white px-1.5 py-0.5 text-sm text-[#16324a] outline-none focus:ring-1 focus:ring-[#1f7fd6]"
                placeholder="输入姓名"
                maxLength={20}
              />
              <button onClick={commitEdit} className="text-success-500 hover:text-success-600">
                <Check className="h-3.5 w-3.5" />
              </button>
              <button onClick={cancelEdit} className="text-[#8fb8dc] hover:text-[#58789b]">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <div className="mt-0.5 text-sm font-medium text-[#16324a]">
              {teacher?.name || '—'}
            </div>
          )}
          <div className="mt-2 flex items-center justify-between">
            <div className="text-xs text-[#58789b]">当前班级</div>
            <Link href="/settings/classes" className="text-xs text-[#1f7fd6] hover:text-[#0e5fa8]">
              管理
            </Link>
          </div>
          <div className="mt-0.5 text-sm font-medium text-[#16324a]">
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
    <aside className="hidden md:flex md:w-60 md:flex-col md:fixed md:inset-y-0 md:left-0 md:z-30 md:border-r md:border-[#cbe2f5] print:hidden">
      <SidebarContent teacher={teacher} onNameChange={onNameChange} />
    </aside>
  )
}
