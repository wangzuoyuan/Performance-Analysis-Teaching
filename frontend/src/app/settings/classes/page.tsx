'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ChevronUp,
  ChevronDown,
  Plus,
  Trash2,
  RefreshCw,
  Star,
  Pencil,
  Users,
  Sparkles,
} from 'lucide-react'

import { useClassScope, formatTeachingClass, type TeachingClass } from '@/lib/class-scope'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const GRADE_LABEL: Record<number, string> = { 1: '高一', 2: '高二', 3: '高三' }

interface ClassMember {
  student_id: string
  name: string
  has_student_id: boolean
  source: 'manual' | 'parser' | 'class_num' | 'roster' | string
  class_num: number | null
  state: 'inherited' | 'new' | 'name_only' | string
}

interface Candidate {
  student_id: string
  name: string
  class_num: number | null
  latest_rank: number | null
}

const SOURCE_LABEL: Record<string, string> = {
  manual: '手动',
  parser: '解析',
  class_num: '班号',
  roster: '花名册',
}

export default function SettingsClassesPage() {
  const { classes, loading, refresh, current, setCurrent } = useClassScope()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [members, setMembers] = useState<ClassMember[]>([])
  const [membersLoading, setMembersLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editingMember, setEditingMember] = useState<ClassMember | null>(null)

  // 自动选中第一个班（仅在无选中且列表非空时）
  useEffect(() => {
    if (selectedId == null && classes.length > 0) {
      setSelectedId(classes[0].id)
    }
  }, [classes, selectedId])

  const selected = useMemo(
    () => classes.find((c) => c.id === selectedId) ?? null,
    [classes, selectedId],
  )

  const loadMembers = useCallback(async (id: number | null) => {
    if (id == null) {
      setMembers([])
      return
    }
    setMembersLoading(true)
    try {
      const data = await fetch(`/api/teaching/classes/${id}/members`).then((r) => r.json())
      setMembers(data.members ?? [])
    } catch {
      setMembers([])
    } finally {
      setMembersLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMembers(selectedId)
  }, [selectedId, loadMembers])

  async function refreshBoth() {
    refresh()
    await loadMembers(selectedId)
  }

  async function setAsCurrent(id: number) {
    setBusy(true)
    setError(null)
    try {
      await fetch('/api/teaching/current', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teaching_class_id: id }),
      })
      await setCurrent(id)
    } catch {
      setError('设为当前班失败')
    } finally {
      setBusy(false)
    }
  }

  async function removeClass(tc: TeachingClass) {
    if (!confirm(`删除「${formatTeachingClass(tc)}」及其成员？此操作不可撤销。`)) return
    setBusy(true)
    setError(null)
    try {
      await fetch(`/api/teaching/classes/${tc.id}`, { method: 'DELETE' })
      if (selectedId === tc.id) setSelectedId(null)
      refresh()
    } catch {
      setError('删除班级失败')
    } finally {
      setBusy(false)
    }
  }

  async function moveClass(tc: TeachingClass, dir: -1 | 1) {
    const ordered = [...classes].sort((a, b) => a.sort_order - b.sort_order)
    const idx = ordered.findIndex((c) => c.id === tc.id)
    const swap = ordered[idx + dir]
    if (!swap) return
    setBusy(true)
    setError(null)
    try {
      await Promise.all([
        fetch(`/api/teaching/classes/${tc.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sort_order: swap.sort_order }),
        }),
        fetch(`/api/teaching/classes/${swap.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sort_order: tc.sort_order }),
        }),
      ])
      refresh()
    } catch {
      setError('排序失败')
    } finally {
      setBusy(false)
    }
  }

  async function syncByClassNum(tc: TeachingClass) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`/api/teaching/classes/${tc.id}/sync-by-class-num`, {
        method: 'POST',
      })
      const data = res.ok ? await res.json() : null
      if (!res.ok) throw new Error()
      setMembers(data.members ?? [])
      refresh()
    } catch {
      setError('按行政班号同步失败（仅行政班可用）')
    } finally {
      setBusy(false)
    }
  }

  async function removeMember(studentId: string) {
    if (!selectedId) return
    setBusy(true)
    setError(null)
    try {
      await fetch(`/api/teaching/classes/${selectedId}/members/${encodeURIComponent(studentId)}`, {
        method: 'DELETE',
      })
      await loadMembers(selectedId)
      refresh()
    } catch {
      setError('移除成员失败')
    } finally {
      setBusy(false)
    }
  }

  // 首次进入、无任何教学班 → 引导面板
  if (!loading && classes.length === 0) {
    return (
      <div className="space-y-4">
        <GettingStarted onCreate={() => setCreateOpen(true)} />
        <CreateClassDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={(id) => {
            refresh()
            setSelectedId(id)
            setCreateOpen(false)
          }}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-slate-500">
          维护「我教的班」及其成员。高一为行政班（数字），高二 / 高三可为走班教学班（如「物A1」）。
        </div>
        <Button onClick={() => setCreateOpen(true)} size="sm">
          <Plus className="h-4 w-4" /> 新建教学班
        </Button>
      </div>

      {error && (
        <div className="rounded-md bg-danger-50 px-3 py-2 text-sm text-danger-600">{error}</div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_1fr]">
        {/* 左列：班级卡片列表 */}
        <div className="space-y-2">
          {loading && <div className="text-sm text-slate-400">加载中…</div>}
          {[...classes]
            .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
            .map((tc, _idx, arr) => {
              const isSel = tc.id === selectedId
              const isCur = tc.id === current
              return (
                <ClassCard
                  key={tc.id}
                  tc={tc}
                  selected={isSel}
                  isCurrent={isCur}
                  onSelect={() => setSelectedId(tc.id)}
                  onSetCurrent={() => setAsCurrent(tc.id)}
                  onEdit={() => setEditOpen(true)}
                  onDelete={() => removeClass(tc)}
                  onMoveUp={
                    tc.id !== arr[0].id ? () => moveClass(tc, -1) : undefined
                  }
                  onMoveDown={
                    tc.id !== arr[arr.length - 1].id ? () => moveClass(tc, 1) : undefined
                  }
                  busy={busy}
                />
              )
            })}
        </div>

        {/* 右列：成员表 */}
        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">
              {selected ? (
                <span>
                  成员管理 · <span className="text-slate-700">{formatTeachingClass(selected)}</span>
                </span>
              ) : (
                '成员管理'
              )}
            </CardTitle>
            {selected?.kind === '行政' && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => syncByClassNum(selected)}
                disabled={busy}
              >
                <RefreshCw className="h-4 w-4" /> 按行政班号同步
              </Button>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            {selected ? (
              <MembersPanel
                tc={selected}
                members={members}
                loading={membersLoading}
                busy={busy}
                onAdded={() => refreshBoth()}
                onRemove={removeMember}
                onEdit={(m) => setEditingMember(m)}
              />
            ) : (
              <div className="py-10 text-center text-sm text-slate-400">
                选择左侧班级以管理成员
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <CreateClassDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => {
          refresh()
          setSelectedId(id)
          setCreateOpen(false)
        }}
      />

      {selected && (
        <EditClassDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          tc={selected}
          onSaved={() => {
            refresh()
            setEditOpen(false)
          }}
        />
      )}

      {selected && editingMember && (
        <EditMemberDialog
          tc={selected}
          member={editingMember}
          onOpenChange={(v) => {
            if (!v) setEditingMember(null)
          }}
          onSaved={() => {
            setEditingMember(null)
            refreshBoth()
          }}
        />
      )}
    </div>
  )
}

/* ──────────────────────────── 引导面板 ──────────────────────────── */

function GettingStarted({ onCreate }: { onCreate: () => void }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-6">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-brand-500" />
          <h2 className="text-lg font-semibold">欢迎使用「班级配置」</h2>
        </div>
        <p className="text-sm text-slate-600">
          在这里维护你教的班级。配置后，仪表盘、对比、学生检索等页面都会按「我教的班」展示，并支持逐班切换。
        </p>
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-md border border-slate-200 p-3 text-sm">
            <div className="mb-1 font-medium">高一</div>
            <div className="text-slate-500">行政班，label 为数字（如 1、6）。</div>
          </div>
          <div className="rounded-md border border-slate-200 p-3 text-sm">
            <div className="mb-1 font-medium">高二 / 高三</div>
            <div className="text-slate-500">走班教学班，label 如「物A1」「史B3」。</div>
          </div>
          <div className="rounded-md border border-slate-200 p-3 text-sm">
            <div className="mb-1 font-medium">成员</div>
            <div className="text-slate-500">行政班一键同步；走班粘贴学号 / 姓名。</div>
          </div>
        </div>
        <div>
          <Button onClick={onCreate}>
            <Plus className="h-4 w-4" /> 创建第一个班级
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* ──────────────────────────── 班卡片 ──────────────────────────── */

function ClassCard(props: {
  tc: TeachingClass
  selected: boolean
  isCurrent: boolean
  busy: boolean
  onSelect: () => void
  onSetCurrent: () => void
  onEdit: () => void
  onDelete: () => void
  onMoveUp?: () => void
  onMoveDown?: () => void
}) {
  const { tc, selected, isCurrent, busy } = props
  return (
    <div
      onClick={props.onSelect}
      className={`cursor-pointer rounded-lg border p-3 transition ${
        selected
          ? 'border-brand-500 bg-brand-50/50 ring-1 ring-brand-500'
          : 'border-slate-200 hover:border-slate-300'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-900">{tc.label}</span>
            <Badge variant="secondary" className="text-xs">
              {GRADE_LABEL[tc.grade] ?? `高${tc.grade}`}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {tc.kind}
            </Badge>
            {tc.subject && (
              <Badge variant="outline" className="text-xs">
                {tc.subject}
              </Badge>
            )}
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <Users className="h-3.5 w-3.5" />
            {tc.member_count} 人
            {isCurrent && (
              <span className="flex items-center gap-0.5 text-success-500">
                <Star className="h-3.5 w-3.5 fill-current" /> 当前班
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1" onClick={(e) => e.stopPropagation()}>
          <div className="flex gap-1">
            <IconBtn title="上移" disabled={!props.onMoveUp || busy} onClick={props.onMoveUp}>
              <ChevronUp className="h-4 w-4" />
            </IconBtn>
            <IconBtn title="下移" disabled={!props.onMoveDown || busy} onClick={props.onMoveDown}>
              <ChevronDown className="h-4 w-4" />
            </IconBtn>
          </div>
          <div className="flex gap-1">
            <IconBtn title="编辑" disabled={busy} onClick={props.onEdit}>
              <Pencil className="h-4 w-4" />
            </IconBtn>
            <IconBtn title="删除" disabled={busy} danger onClick={props.onDelete}>
              <Trash2 className="h-4 w-4" />
            </IconBtn>
          </div>
        </div>
      </div>
      {!isCurrent && (
        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={props.onSetCurrent} disabled={busy}>
            <Star className="h-3.5 w-3.5" /> 设为当前班
          </Button>
        </div>
      )}
    </div>
  )
}

function IconBtn(props: {
  title: string
  onClick?: () => void
  disabled?: boolean
  danger?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={props.title}
      disabled={props.disabled}
      onClick={props.onClick}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-md border border-slate-200 text-slate-600 transition hover:bg-slate-100 disabled:opacity-40 ${
        props.danger ? 'hover:bg-danger-50 hover:text-danger-600' : ''
      }`}
    >
      {props.children}
    </button>
  )
}

/* ──────────────────────────── 成员面板 ──────────────────────────── */

function MembersPanel(props: {
  tc: TeachingClass
  members: ClassMember[]
  loading: boolean
  busy: boolean
  onAdded: () => void
  onRemove: (studentId: string) => void
  onEdit: (m: ClassMember) => void
}) {
  const { tc, members, loading, busy } = props
  const [tab, setTab] = useState<'table' | 'add' | 'import'>('table')

  return (
    <div className="space-y-3">
      <div className="flex gap-1 overflow-x-auto">
        {(['table', 'add', 'import'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm transition ${
              tab === t
                ? 'bg-brand-500 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {t === 'table' ? '成员列表' : t === 'add' ? '添加成员' : '批量导入'}
          </button>
        ))}
      </div>

      {tab === 'table' && (
        <>
          {loading ? (
            <div className="py-8 text-center text-sm text-slate-400">加载中…</div>
          ) : members.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-400">
              暂无成员。
              {tc.kind === '行政'
                ? '可点「按行政班号同步」自动导入。'
                : '可在「添加成员」或「批量导入」中添加。'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-32">学号</TableHead>
                    <TableHead>姓名</TableHead>
                    <TableHead className="w-20">来源</TableHead>
                    <TableHead className="w-20">行政班</TableHead>
                    <TableHead className="w-20">状态</TableHead>
                    <TableHead className="w-24 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((m) => (
                    <TableRow key={m.student_id}>
                      <TableCell className="font-mono text-xs">
                        {m.has_student_id ? (
                          m.student_id
                        ) : (
                          <Badge variant="outline" className="text-xs text-slate-400">
                            未设置
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>{m.name}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {SOURCE_LABEL[m.source] ?? m.source}
                        </Badge>
                      </TableCell>
                      <TableCell>{m.class_num ?? '—'}</TableCell>
                      <TableCell>
                        {m.state === 'name_only' ? (
                          <Badge variant="outline" className="text-xs text-slate-400">仅姓名</Badge>
                        ) : m.state === 'new' ? (
                          <Badge variant="warning" className="text-xs">新生</Badge>
                        ) : (
                          <Badge variant="success" className="text-xs">老生</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <IconBtn
                            title={m.has_student_id ? '修改学号 / 姓名' : '补录学号'}
                            disabled={busy}
                            onClick={() => props.onEdit(m)}
                          >
                            <Pencil className="h-4 w-4" />
                          </IconBtn>
                          <IconBtn title="移除" disabled={busy} danger onClick={() => props.onRemove(m.student_id)}>
                            <Trash2 className="h-4 w-4" />
                          </IconBtn>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </>
      )}

      {tab === 'add' && <AddMembersPanel tc={tc} busy={busy} onAdded={props.onAdded} />}

      {tab === 'import' && <ImportMembersPanel tc={tc} busy={busy} onAdded={props.onAdded} />}
    </div>
  )
}

function AddMembersPanel(props: {
  tc: TeachingClass
  busy: boolean
  onAdded: () => void
}) {
  const { tc, busy } = props
  const [mode, setMode] = useState<'ids' | 'names'>('ids')
  const [value, setValue] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [ambiguous, setAmbiguous] = useState<{ name: string; candidate_ids: string[] }[] | null>(null)

  async function submit() {
    const tokens = value
      .split(/[\n,，;；\s]+/)
      .map((t) => t.trim())
      .filter(Boolean)
    if (tokens.length === 0) return
    setMsg(null)
    setAmbiguous(null)
    try {
      const body = mode === 'ids' ? { student_ids: tokens } : { names: tokens }
      const res = await fetch(`/api/teaching/classes/${tc.id}/members`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = res.ok ? await res.json() : null
      if (!res.ok) {
        setMsg('添加失败')
        return
      }
      const added: number = data.added ?? 0
      const amb: { name: string; candidate_ids: string[] }[] = data.ambiguous ?? []
      const noId: number = (data.name_only ?? []).length
      setMsg(
        `已添加 ${added} 人。${noId ? `${noId} 人仅录姓名（暂无学号，可日后补）。` : ''}${
          amb.length ? `${amb.length} 个姓名需消歧。` : ''
        }`,
      )
      if (amb.length) setAmbiguous(amb)
      setValue('')
      props.onAdded()
    } catch {
      setMsg('添加失败')
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        <Select value={mode} onValueChange={(v) => setMode(v as 'ids' | 'names')}>
          <SelectTrigger className="h-9 w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ids">按学号</SelectItem>
            <SelectItem value="names">按姓名</SelectItem>
          </SelectContent>
        </Select>
        <Button onClick={submit} disabled={busy} size="sm">
          添加
        </Button>
      </div>
      <p className="text-xs text-slate-500">
        {mode === 'ids'
          ? '一行一个学号（或逗号 / 空格分隔），直接加入。'
          : '一行一个姓名；唯一命中自动加入，同名返回候选供确认，无匹配则按姓名先加入（日后可补学号）。'}
      </p>
      <textarea
        className="min-h-[120px] w-full rounded-md border border-slate-200 p-2 text-sm"
        placeholder={mode === 'ids' ? '如：20230101\n20230102' : '如：张三\n李四'}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      {msg && <div className="text-sm text-slate-600">{msg}</div>}
      {ambiguous && ambiguous.length > 0 && (
        <AmbiguousBlock
          tc={tc}
          items={ambiguous}
          busy={busy}
          onPicked={() => {
            setAmbiguous(null)
            props.onAdded()
          }}
        />
      )}
    </div>
  )
}

/* 同名消歧：列出候选（学号 / 行政班 / 最近名次），老师点选其一用学号加入 */
function AmbiguousBlock(props: {
  tc: TeachingClass
  items: { name: string; candidate_ids: string[] }[]
  busy: boolean
  onPicked: () => void
}) {
  const { tc, items, busy } = props
  const [detail, setDetail] = useState<Record<string, Candidate[] | undefined>>({})
  const [loadingName, setLoadingName] = useState<string | null>(null)

  async function resolve(item: { name: string; candidate_ids: string[] }) {
    setLoadingName(item.name)
    try {
      // 候选已给出学号，再补全 class_num / latest_rank：复用 name-candidates 接口
      const res = await fetch(
        `/api/teaching/name-candidates?name=${encodeURIComponent(item.name)}&grade=${tc.grade}`,
      )
      const data = res.ok ? await res.json() : null
      const cands: Candidate[] = (data?.candidates ?? []).map((c: Candidate & { latest_rank?: number }) => ({
        student_id: c.student_id,
        name: c.name,
        class_num: c.class_num ?? null,
        latest_rank: c.latest_rank ?? null,
      }))
      // 仅保留本次消歧的候选
      const allowed = new Set(item.candidate_ids)
      setDetail((d) => ({ ...d, [item.name]: cands.filter((c) => allowed.has(c.student_id)) }))
    } finally {
      setLoadingName(null)
    }
  }

  return (
    <div className="space-y-3 rounded-md border border-warning-200 bg-warning-50/50 p-3">
      <div className="text-sm font-medium text-warning-600">同名待确认</div>
      {items.map((item) => (
        <div key={item.name} className="space-y-1">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">{item.name}</span>
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" disabled={busy} onClick={() => resolve(item)}>
              查看候选
            </Button>
          </div>
          {loadingName === item.name && <div className="text-xs text-slate-400">加载候选…</div>}
          {detail[item.name] && (
            <div className="flex flex-wrap gap-2">
              {detail[item.name]!.length === 0 && (
                <span className="text-xs text-slate-400">无候选信息</span>
              )}
              {detail[item.name]!.map((c) => (
                <PickCandidateButton
                  key={c.student_id}
                  candidate={c}
                  disabled={busy}
                  onPick={async () => {
                    await fetch(`/api/teaching/classes/${tc.id}/members`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ student_ids: [c.student_id] }),
                    })
                    props.onPicked()
                  }}
                />
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function PickCandidateButton(props: {
  candidate: Candidate
  disabled?: boolean
  onPick: () => void
}) {
  const { candidate } = props
  return (
    <button
      type="button"
      disabled={props.disabled}
      onClick={props.onPick}
      className="rounded-md border border-slate-200 bg-white px-2 py-1 text-left text-xs hover:border-brand-400 hover:bg-brand-50 disabled:opacity-40"
    >
      <div className="font-mono text-slate-700">{candidate.student_id}</div>
      <div className="text-slate-500">
        {candidate.class_num != null ? `${candidate.class_num}班 · ` : ''}
        {candidate.latest_rank != null ? `名次 ${candidate.latest_rank}` : '无成绩'}
      </div>
    </button>
  )
}

/* 批量导入：粘贴「学号 姓名」/ 姓名 / 学号清单，展示解析结果 */
function ImportMembersPanel(props: {
  tc: TeachingClass
  busy: boolean
  onAdded: () => void
}) {
  const { tc, busy } = props
  const [text, setText] = useState('')
  const [upsert, setUpsert] = useState(false)
  const [result, setResult] = useState<{
    matched: { student_id: string; name: string; state: 'inherited' | 'new' | string }[]
    name_only: { student_id: string; name: string; state: string }[]
    ambiguous: { name: string; candidates: Candidate[] }[]
    unmatched: { token: string; name: string }[]
    added_count: number
    reassigned_count: number
  } | null>(null)
  const [busy2, setBusy2] = useState(false)

  async function submit() {
    if (!text.trim()) return
    setBusy2(true)
    try {
      const res = await fetch(`/api/teaching/classes/${tc.id}/members/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, upsert }),
      })
      const data = res.ok ? await res.json() : null
      if (!res.ok || !data) {
        setResult(null)
        return
      }
      setResult(data)
      props.onAdded()
    } finally {
      setBusy2(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        每行一个，支持三种写法（自动判别）：
        <span className="ml-1 text-slate-700">「学号 姓名」</span>成对录入；
        <span className="ml-1 text-slate-700">单学号</span>直接加入；
        <span className="ml-1 text-slate-700">单姓名</span>唯一命中加入、无匹配则先按姓名加入（日后可补学号）。
      </p>
      <textarea
        className="min-h-[160px] w-full rounded-md border border-slate-200 p-2 text-sm"
        placeholder={'每行一个，例如：\n7250601 张三\n7250602 李四\n王五'}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={submit} disabled={busy || busy2} size="sm">
          解析并导入
        </Button>
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={upsert}
            onChange={(e) => setUpsert(e.target.checked)}
            className="h-3.5 w-3.5"
          />
          覆盖模式：按姓名匹配并更新已有成员的学号（学号变更后整表重导用）
        </label>
      </div>

      {result && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge variant="success">已匹配 {result.matched.length}</Badge>
            <Badge variant="outline">仅姓名 {result.name_only.length}</Badge>
            <Badge variant="warning">待消歧 {result.ambiguous.length}</Badge>
            <Badge variant="destructive">未匹配 {result.unmatched.length}</Badge>
            <span className="self-center text-slate-500">
              新增 {result.added_count} 人
              {result.reassigned_count > 0 && ` · 覆盖 ${result.reassigned_count} 人学号`}
            </span>
          </div>

          {result.matched.length > 0 && (
            <div className="rounded-md border border-slate-200">
              <div className="border-b border-slate-100 px-3 py-1.5 text-xs font-medium text-slate-500">
                已匹配
              </div>
              <div className="flex flex-wrap gap-1.5 p-3">
                {result.matched.map((m) => (
                  <Badge
                    key={m.student_id}
                    variant={m.state === 'new' ? 'warning' : 'outline'}
                    className="font-mono text-xs"
                  >
                    {m.name}
                    <span className="ml-1 opacity-70">{m.student_id}</span>
                    {m.state === 'new' && <span className="ml-1">新生</span>}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {result.name_only.length > 0 && (
            <div className="rounded-md border border-slate-200 bg-slate-50/50">
              <div className="border-b border-slate-100 px-3 py-1.5 text-xs font-medium text-slate-500">
                仅录入姓名（暂无学号，可在成员列表里逐个补录）
              </div>
              <div className="flex flex-wrap gap-1.5 p-3">
                {result.name_only.map((m) => (
                  <Badge key={m.student_id} variant="outline" className="text-xs">
                    {m.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {result.ambiguous.length > 0 && (
            <ImportAmbiguousBlock tc={tc} items={result.ambiguous} busy={busy} onPicked={props.onAdded} />
          )}

          {result.unmatched.length > 0 && (
            <div className="rounded-md border border-danger-200 bg-danger-50/40">
              <div className="border-b border-danger-100 px-3 py-1.5 text-xs font-medium text-danger-600">
                未匹配
              </div>
              <div className="flex flex-wrap gap-1.5 p-3">
                {result.unmatched.map((u) => (
                  <Badge key={u.token} variant="destructive" className="text-xs">
                    {u.name || u.token}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ImportAmbiguousBlock(props: {
  tc: TeachingClass
  items: { name: string; candidates: Candidate[] }[]
  busy: boolean
  onPicked: () => void
}) {
  const { tc, items, busy } = props
  return (
    <div className="rounded-md border border-warning-200 bg-warning-50/50">
      <div className="border-b border-warning-100 px-3 py-1.5 text-xs font-medium text-warning-600">
        同名待确认（点选正确学生用学号加入）
      </div>
      <div className="space-y-2 p-3">
        {items.map((item) => (
          <div key={item.name} className="space-y-1">
            <div className="text-sm font-medium">{item.name}</div>
            <div className="flex flex-wrap gap-2">
              {item.candidates.map((c) => (
                <PickCandidateButton
                  key={c.student_id}
                  candidate={c}
                  disabled={busy}
                  onPick={async () => {
                    await fetch(`/api/teaching/classes/${tc.id}/members`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ student_ids: [c.student_id] }),
                    })
                    props.onPicked()
                  }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ──────────────────────────── 新建 / 编辑班级 ──────────────────────────── */

function CreateClassDialog(props: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: (id: number) => void
}) {
  const { open, onOpenChange, onCreated } = props
  const [grade, setGrade] = useState<number>(1)
  const [label, setLabel] = useState('')
  const [subject, setSubject] = useState('')
  const [teacherSubject, setTeacherSubject] = useState<string | null>(null)
  const [kind, setKind] = useState<'行政' | '教学'>('行政')
  const [candidates, setCandidates] = useState<{ class_nums: number[]; class_labels: string[] }>({
    class_nums: [],
    class_labels: [],
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // 打开 / 年级变化 → 拉候选
  useEffect(() => {
    if (!open) return
    setKind(grade === 1 ? '行政' : '教学')
    fetch(`/api/teaching/candidate-classes?grade=${grade}`)
      .then((r) => (r.ok ? r.json() : { class_nums: [], class_labels: [] }))
      .then((d) =>
        setCandidates({ class_nums: d.class_nums ?? [], class_labels: d.class_labels ?? [] }),
      )
      .catch(() => setCandidates({ class_nums: [], class_labels: [] }))
  }, [open, grade])

  useEffect(() => {
    if (!open) return
    fetch('/api/teacher')
      .then(async (res) => {
        const data = await res.json().catch(() => null)
        if (!res.ok) throw new Error(data?.detail || '无法读取任教学科')
        const configured = typeof data?.subject === 'string' ? data.subject : null
        setTeacherSubject(configured)
        setSubject(configured ?? '')
      })
      .catch((error) => setErr(error instanceof Error ? error.message : '无法读取任教学科'))
  }, [open])

  function reset() {
    setLabel('')
    setSubject('')
    setErr(null)
  }

  async function submit() {
    const lbl = label.trim()
    if (!lbl) {
      setErr('请填写班名')
      return
    }
    if (!subject.trim()) {
      setErr('请填写任教学科；首次设置后所有班级都只分析该学科')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const res = await fetch('/api/teaching/classes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          grade,
          label: lbl,
          subject: subject.trim() || null,
          kind,
        }),
      })
      const data = await res.json().catch(() => null)
      if (!res.ok) {
        setErr(data?.detail || '创建失败')
        return
      }
      reset()
      onCreated(data.id)
    } catch {
      setErr('创建失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) reset() }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>新建教学班</DialogTitle>
          <DialogDescription>
            高一选「行政」并填数字班号；高二 / 高三选「教学」并填走班名（如 物A1）。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Field label="年级">
            <Select value={String(grade)} onValueChange={(v) => setGrade(Number(v))}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">高一</SelectItem>
                <SelectItem value="2">高二</SelectItem>
                <SelectItem value="3">高三</SelectItem>
              </SelectContent>
            </Select>
          </Field>

          <Field label="班名（label）">
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={grade === 1 ? '如 1、6' : '如 物A1、史B3'}
            />
          </Field>
          {candidates.class_nums.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {candidates.class_nums.map((n) => (
                <CandidateChip key={`n${n}`} label={String(n)} onClick={() => setLabel(String(n))} />
              ))}
              {candidates.class_labels.map((l) => (
                <CandidateChip key={`l${l}`} label={l} onClick={() => setLabel(l)} />
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <Field label="类型">
              <Select value={kind} onValueChange={(v) => setKind(v as '行政' | '教学')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="行政">行政班</SelectItem>
                  <SelectItem value="教学">教学班</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label={teacherSubject ? '任教学科' : '任教学科（首次必填）'}>
              <Input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="如 物理"
                disabled={teacherSubject != null}
              />
            </Field>
          </div>

          {err && <div className="text-sm text-danger-600">{err}</div>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy}>
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CandidateChip(props: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-600 hover:border-brand-400 hover:text-brand-600"
    >
      {props.label}
    </button>
  )
}

function EditClassDialog(props: {
  open: boolean
  onOpenChange: (v: boolean) => void
  tc: TeachingClass
  onSaved: () => void
}) {
  const { open, onOpenChange, tc, onSaved } = props
  const [label, setLabel] = useState(tc.label)
  const [subject, setSubject] = useState(tc.subject ?? '')
  const [kind, setKind] = useState<'行政' | '教学'>(tc.kind as '行政' | '教学')
  const [note, setNote] = useState(tc.note ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setLabel(tc.label)
      setSubject(tc.subject ?? '')
      setKind(tc.kind as '行政' | '教学')
      setNote(tc.note ?? '')
      setErr(null)
    }
  }, [open, tc])

  async function submit() {
    setBusy(true)
    setErr(null)
    try {
      const res = await fetch(`/api/teaching/classes/${tc.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: label.trim() || undefined,
          subject: subject.trim() || null,
          kind,
          note: note.trim() || null,
        }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => null)
        setErr(d?.detail || '保存失败')
        return
      }
      onSaved()
    } catch {
      setErr('保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>编辑班级</DialogTitle>
          <DialogDescription>{formatTeachingClass(tc)}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="班名（label）">
            <Input value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="类型">
              <Select value={kind} onValueChange={(v) => setKind(v as '行政' | '教学')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="行政">行政班</SelectItem>
                  <SelectItem value="教学">教学班</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="任教学科">
              <Input value={subject} disabled />
            </Field>
          </div>
          <Field label="备注（可选）">
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {err && <div className="text-sm text-danger-600">{err}</div>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field(props: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-slate-500">{props.label}</label>
      {props.children}
    </div>
  )
}

/* 编辑单个成员：补录 / 修改学号，可同时改姓名。改学号会连带迁移档案、缺交等数据。 */
function EditMemberDialog(props: {
  tc: TeachingClass
  member: ClassMember
  onOpenChange: (v: boolean) => void
  onSaved: () => void
}) {
  const { tc, member, onOpenChange, onSaved } = props
  const [sid, setSid] = useState(member.has_student_id ? member.student_id : '')
  const [name, setName] = useState(member.name ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    setSid(member.has_student_id ? member.student_id : '')
    setName(member.name ?? '')
    setErr(null)
  }, [member])

  async function submit() {
    const newId = sid.trim()
    if (!newId) {
      setErr('请填写学号')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const res = await fetch(
        `/api/teaching/classes/${tc.id}/members/${encodeURIComponent(member.student_id)}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_student_id: newId, name: name.trim() || undefined }),
        },
      )
      if (!res.ok) {
        const d = await res.json().catch(() => null)
        setErr(d?.detail || '保存失败')
        return
      }
      onSaved()
    } catch {
      setErr('保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{member.has_student_id ? '修改学号 / 姓名' : '补录学号'}</DialogTitle>
          <DialogDescription>
            {member.has_student_id
              ? `「${member.name}」当前学号 ${member.student_id}`
              : `「${member.name}」目前仅录入了姓名，尚未绑定学号`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="学号">
            <Input
              value={sid}
              onChange={(e) => setSid(e.target.value)}
              placeholder="如 7250601"
              className="font-mono"
            />
          </Field>
          <Field label="姓名">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <p className="text-xs text-slate-500">
            改学号后，该生的成长档案、缺交记录会随之迁移到新学号；历史成绩不受影响（跨学年学号变更请用「身份链接」）。
          </p>
          {err && <div className="text-sm text-danger-600">{err}</div>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
