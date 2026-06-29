'use client'

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

/** 一个教学班（老师配置的班：高一=行政班数字，高二/三可为走班名如「物A1」）。 */
export interface TeachingClass {
  id: number
  grade: number
  label: string
  subject?: string | null
  kind: string // 行政 / 教学
  note?: string | null
  sort_order: number
  member_count: number
  created_at?: string | null
}

type ScopeValue = number | 'all'

interface ClassScopeContextValue {
  classes: TeachingClass[]
  loading: boolean
  /** 当前选中的教学班 id，或 'all'（我教的所有班并集）。 */
  current: ScopeValue
  currentClass: TeachingClass | null
  setCurrent: (v: ScopeValue) => void
  refresh: () => void
  /** 生成请求参数：选定具体教学班、且（如给了 grade）年级匹配时返回 {teaching_class_id}，否则 {}。
   *  分析页用 `const params = scopeParam(grade)` 拼到 fetch URL。 */
  scopeParam: (grade?: number) => { teaching_class_id?: number }
  /** 某年级下的可选班列表。 */
  classesForGrade: (grade?: number) => TeachingClass[]
}

const ClassScopeContext = createContext<ClassScopeContextValue | null>(null)

export function ClassScopeProvider({ children }: { children: ReactNode }) {
  const [classes, setClasses] = useState<TeachingClass[]>([])
  const [loading, setLoading] = useState(true)
  const [current, setCurrentState] = useState<ScopeValue>('all')

  const fetchClasses = useCallback(async () => {
    try {
      const res = await fetch('/api/teaching/classes')
      const data = res.ok ? await res.json() : { classes: [] }
      setClasses(data.classes ?? [])
    } catch {
      setClasses([])
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchCurrent = useCallback(async () => {
    try {
      const res = await fetch('/api/teaching/current')
      const data = res.ok ? await res.json() : null
      const id = data?.teaching_class_id
      setCurrentState(id != null ? id : 'all')
    } catch {
      setCurrentState('all')
    }
  }, [])

  useEffect(() => {
    fetchClasses()
    fetchCurrent()
  }, [fetchClasses, fetchCurrent])

  const setCurrent = useCallback(async (v: ScopeValue) => {
    setCurrentState(v)
    try {
      await fetch('/api/teaching/current', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teaching_class_id: v === 'all' ? null : v }),
      })
      if (typeof window !== 'undefined') localStorage.setItem('classScope', String(v))
    } catch {
      /* silent */
    }
  }, [])

  const refresh = useCallback(() => {
    fetchClasses()
  }, [fetchClasses])

  const currentClass = current === 'all' ? null : classes.find((c) => c.id === current) ?? null

  const scopeParam = useCallback(
    (grade?: number) => {
      if (current === 'all') return {}
      const tc = classes.find((c) => c.id === current)
      if (!tc) return {}
      if (grade != null && tc.grade !== grade) return {}
      return { teaching_class_id: current }
    },
    [current, classes],
  )

  const classesForGrade = useCallback(
    (grade?: number) => (grade == null ? classes : classes.filter((c) => c.grade === grade)),
    [classes],
  )

  return (
    <ClassScopeContext.Provider
      value={{ classes, loading, current, currentClass, setCurrent, refresh, scopeParam, classesForGrade }}
    >
      {children}
    </ClassScopeContext.Provider>
  )
}

export function useClassScope(): ClassScopeContextValue {
  const ctx = useContext(ClassScopeContext)
  if (!ctx) throw new Error('useClassScope must be used within ClassScopeProvider')
  return ctx
}

/** 把 {grade,label} 拼成展示串，如「高二·物A1」「高一·1」。 */
export function formatTeachingClass(tc: { grade: number; label: string } | null | undefined): string | null {
  if (!tc) return null
  const g = { 1: '高一', 2: '高二', 3: '高三' }[tc.grade] ?? `高${tc.grade}`
  return `${g}·${tc.label}`
}

/** 列表/学生旁徽章用的简短标签。 */
export function formatClassChip(label: string | null | undefined): string | null {
  if (!label) return null
  return label
}
