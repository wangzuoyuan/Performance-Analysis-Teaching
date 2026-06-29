'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import {
  Check,
  FileSpreadsheet,
  History,
  Loader2,
  UploadCloud,
  X,
  AlertTriangle,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { formatClassLabel, formatGradeLabel } from '@/lib/labels'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

type StepKey = 'file' | 'done'

interface UploadResult {
  filename: string
  parsed_ok: boolean
  message?: string
  kind?: string
  grade?: number
}

interface UploadResponse {
  results: UploadResult[]
  detected_class?: number
  detected_grade?: number
}

const KIND_LABEL: Record<string, string> = {
  student_scores: '学生分数表',
  class_averages: '班级均分表',
  rank_bands: '名次段表',
  unknown: '未识别',
}

// 上传确认时可编辑的单文件元数据
interface PreviewItem {
  token: string
  filename: string
  grade: number
  semester: '上' | '下'
  exam_type: string
  year: number | null
  month: number | null
  canonical_name?: string | null
  is_xlsx?: boolean
}

const GRADE_OPTS = [
  { v: 1, l: '高一' },
  { v: 2, l: '高二' },
  { v: 3, l: '高三' },
]
const SEMESTER_OPTS: Array<{ v: '上' | '下'; l: string }> = [
  { v: '上', l: '第一学期' },
  { v: '下', l: '第二学期' },
]
const EXAM_TYPE_OPTS = ['月考', '期中', '期末', '一模', '二模', '三模']

function yearOptions(): number[] {
  const base = new Date().getFullYear()
  // 覆盖前两年到后一年，足够覆盖跨学年录入
  return Array.from({ length: 6 }, (_, i) => base - 2 + i)
}
function monthOptions(): number[] {
  return Array.from({ length: 12 }, (_, i) => i + 1)
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

interface StepDef {
  key: StepKey
  index: number
  title: string
}

const STEPS: StepDef[] = [
  { key: 'file', index: 1, title: '选择 Excel 文件' },
  { key: 'done', index: 2, title: '解析与确认' },
]

function StepIndicator({
  currentStep,
  completed,
}: {
  currentStep: StepKey
  completed: Record<StepKey, boolean>
}) {
  const currentIdx = STEPS.findIndex((s) => s.key === currentStep)

  return (
    <div className="flex items-center">
      {STEPS.map((step, i) => {
        const isDone = completed[step.key]
        const isActive = step.key === currentStep && !isDone
        const isPending = !isDone && !isActive

        return (
          <div key={step.key} className="flex flex-1 items-center">
            <div className="flex items-center gap-3">
              <div
                className={cn(
                  'flex h-9 w-9 items-center justify-center rounded-full text-sm font-semibold transition-colors',
                  isDone && 'bg-success-500 text-white',
                  isActive && 'bg-brand-500 text-white',
                  isPending && 'bg-slate-200 text-slate-500'
                )}
              >
                {isDone ? <Check className="h-5 w-5" /> : step.index}
              </div>
              <div className="hidden sm:block">
                <div
                  className={cn(
                    'text-sm font-medium',
                    isDone && 'text-success-500',
                    isActive && 'text-brand-700',
                    isPending && 'text-slate-500'
                  )}
                >
                  {step.title}
                </div>
              </div>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={cn(
                  'mx-4 h-px flex-1 border-t border-dashed',
                  i < currentIdx || completed[STEPS[i + 1].key]
                    ? 'border-success-500'
                    : 'border-slate-300'
                )}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function UploadPage() {
  const [step, setStep] = useState<StepKey>('file')
  const [completed, setCompleted] = useState<Record<StepKey, boolean>>({
    file: false,
    done: false,
  })

  // 文件上传
  const [files, setFiles] = useState<File[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 解析结果
  const [results, setResults] = useState<UploadResult[]>([])
  const [detectedClass, setDetectedClass] = useState<number | null>(null)
  const [detectedGrade, setDetectedGrade] = useState<number | null>(null)
  const [resultOpen, setResultOpen] = useState(false)

  // 上传确认（逐文件可编辑年级/年月）
  const [previewItems, setPreviewItems] = useState<PreviewItem[]>([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [committing, setCommitting] = useState(false)

  function addFiles(incoming: FileList | File[]) {
    const next = Array.from(incoming).filter((f) => f.name.toLowerCase().endsWith('.xlsx'))
    if (next.length === 0) return
    setFiles((prev) => {
      // 去重（按 name + size）
      const seen = new Set(prev.map((f) => `${f.name}::${f.size}`))
      const merged = [...prev]
      for (const f of next) {
        const key = `${f.name}::${f.size}`
        if (!seen.has(key)) {
          merged.push(f)
          seen.add(key)
        }
      }
      return merged
    })
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  // 阶段一：上传并取回每个文件的自动识别建议，弹出确认表单
  async function handlePreview() {
    if (files.length === 0) return
    setUploading(true)
    setUploadError(null)

    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))

    try {
      const res = await fetch('/api/uploads/preview', { method: 'POST', body: formData })
      if (!res.ok) {
        throw new Error(`识别失败（HTTP ${res.status}）`)
      }
      const data: { files?: PreviewItem[] } = await res.json()
      const thisYear = new Date().getFullYear()
      const items: PreviewItem[] = (data.files || []).map((it) => ({
        token: it.token,
        filename: it.filename,
        grade: it.grade ?? 1,
        semester: it.semester === '下' ? '下' : '上',
        exam_type: it.exam_type ?? '月考',
        year: it.year ?? thisYear,
        month: it.month ?? 9,
        canonical_name: it.canonical_name,
        is_xlsx: it.is_xlsx,
      }))
      setPreviewItems(items)
      setConfirmOpen(true)
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : '识别过程中发生未知错误')
    } finally {
      setUploading(false)
    }
  }

  function updateItem(idx: number, patch: Partial<PreviewItem>) {
    setPreviewItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)))
  }

  // 阶段二：按确认后的元数据正式入库
  async function handleCommit() {
    if (previewItems.length === 0) return
    setCommitting(true)
    setUploadError(null)

    try {
      const res = await fetch('/api/uploads/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: previewItems.map((it) => ({
            token: it.token,
            grade: it.grade,
            semester: it.semester,
            exam_type: it.exam_type,
            year: it.year,
            month: it.month,
          })),
        }),
      })
      if (!res.ok) {
        throw new Error(`入库失败（HTTP ${res.status}）`)
      }
      const data: UploadResponse = await res.json()
      setResults(data.results || [])
      setDetectedClass(data.detected_class ?? null)
      setDetectedGrade(data.detected_grade ?? null)
      setCompleted((c) => ({ ...c, file: true, done: true }))
      setStep('done')
      setConfirmOpen(false)
      setResultOpen(true)
      setFiles([])
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : '入库过程中发生未知错误')
    } finally {
      setCommitting(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 顶部 */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">数据上传</h1>
          <p className="mt-1 text-sm text-slate-500">
            上传学生分数表 / 班级均分表 / 名次段表（.xlsx）。班级在「班级配置」里维护，上传后自动归类。
          </p>
        </div>
        <Button variant="outline" disabled title="即将上线">
          <History className="mr-1 h-4 w-4" />
          查看上传历史
        </Button>
      </div>

      {/* 步骤指示器 */}
      <Card>
        <CardContent className="py-5">
          <StepIndicator currentStep={step} completed={completed} />
        </CardContent>
      </Card>

      {/* Step 1: 上传文件 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Step 1 · 选择 Excel 文件</CardTitle>
          <CardDescription>
            支持一次拖入多份 .xlsx；学生分数表 / 班级均分表 / 名次段表均可
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setIsDragging(false)
              addFiles(e.dataTransfer.files)
            }}
            onClick={() => inputRef.current?.click()}
            className={cn(
              'flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors',
              isDragging
                ? 'border-brand-500 bg-brand-50'
                : 'border-slate-300 hover:border-brand-500 hover:bg-brand-50'
            )}
          >
            <UploadCloud
              className={cn(
                'h-12 w-12 transition-colors',
                isDragging ? 'text-brand-500' : 'text-slate-400'
              )}
            />
            <p className="mt-3 text-sm text-slate-600">
              拖入 Excel 文件，或
              <span className="ml-1 font-medium text-brand-600">点击选择文件</span>
            </p>
            <p className="mt-1 text-xs text-slate-400">仅支持 .xlsx，可多选</p>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".xlsx"
              className="hidden"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files)
                e.target.value = ''
              }}
            />
          </div>

          {files.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
                已选择 {files.length} 个文件
              </div>
              <div className="space-y-2">
                {files.map((f, i) => (
                  <Card key={`${f.name}-${i}`} className="border-slate-200">
                    <CardContent className="flex items-center gap-3 py-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-brand-50 text-brand-600">
                        <FileSpreadsheet className="h-5 w-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-slate-800">
                          {f.name}
                        </div>
                        <div className="text-xs text-slate-500">{formatBytes(f.size)}</div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={(e) => {
                          e.stopPropagation()
                          removeFile(i)
                        }}
                        disabled={uploading}
                        aria-label="移除"
                      >
                        <X className="h-4 w-4 text-slate-500" />
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {uploading && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <Loader2 className="h-4 w-4 animate-spin text-brand-600" />
                正在识别考试信息…
              </div>
              {/* 后端不返回进度，使用不定值动画 */}
              <Progress value={66} className="animate-pulse" />
            </div>
          )}

          {uploadError && (
            <Card className="border-danger-500 bg-danger-50">
              <CardContent className="flex items-start gap-2 py-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-danger-500" />
                <div className="text-sm text-danger-500">{uploadError}</div>
              </CardContent>
            </Card>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setFiles([])}
              disabled={files.length === 0 || uploading}
            >
              清空
            </Button>
            <Button onClick={handlePreview} disabled={files.length === 0 || uploading}>
              {uploading ? (
                <>
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  识别中
                </>
              ) : (
                <>
                  <UploadCloud className="mr-1 h-4 w-4" />
                  下一步：确认考试信息
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Step 3a: 确认考试信息（逐文件可编辑年级/年月） */}
      <Dialog open={confirmOpen} onOpenChange={(o) => !committing && setConfirmOpen(o)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>确认考试信息</DialogTitle>
            <DialogDescription>
              下方是按文件名的自动识别结果，请核对「年级」和「考试年月」（决定排序）后再入库。
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
            {previewItems.map((it, i) => (
              <Card key={`${it.token}-${i}`} className="border-slate-200">
                <CardContent className="space-y-3 py-3">
                  <div className="flex items-center gap-2">
                    <FileSpreadsheet className="h-4 w-4 shrink-0 text-brand-600" />
                    <span className="truncate text-sm font-medium text-slate-800">
                      {it.filename}
                    </span>
                    {it.is_xlsx === false && (
                      <Badge variant="destructive">非 .xlsx，无法解析</Badge>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                    <div className="space-y-1">
                      <label className="text-xs text-slate-500">年级</label>
                      <Select
                        value={String(it.grade)}
                        onValueChange={(v) => updateItem(i, { grade: Number(v) })}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {GRADE_OPTS.map((o) => (
                            <SelectItem key={o.v} value={String(o.v)}>
                              {o.l}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-500">学期</label>
                      <Select
                        value={it.semester}
                        onValueChange={(v) => updateItem(i, { semester: v as '上' | '下' })}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {SEMESTER_OPTS.map((o) => (
                            <SelectItem key={o.v} value={o.v}>
                              {o.l}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-500">类型</label>
                      <Select
                        value={it.exam_type}
                        onValueChange={(v) => updateItem(i, { exam_type: v })}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {EXAM_TYPE_OPTS.map((o) => (
                            <SelectItem key={o} value={o}>
                              {o}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-500">年份</label>
                      <Select
                        value={it.year != null ? String(it.year) : ''}
                        onValueChange={(v) => updateItem(i, { year: Number(v) })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="年" />
                        </SelectTrigger>
                        <SelectContent>
                          {yearOptions().map((y) => (
                            <SelectItem key={y} value={String(y)}>
                              {y} 年
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs text-slate-500">月份</label>
                      <Select
                        value={it.month != null ? String(it.month) : ''}
                        onValueChange={(v) => updateItem(i, { month: Number(v) })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="月" />
                        </SelectTrigger>
                        <SelectContent>
                          {monthOptions().map((m) => (
                            <SelectItem key={m} value={String(m)}>
                              {m} 月
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
            {previewItems.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
                没有可确认的文件
              </div>
            )}
          </div>

          {uploadError && (
            <Card className="border-danger-500 bg-danger-50">
              <CardContent className="flex items-start gap-2 py-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-danger-500" />
                <div className="text-sm text-danger-500">{uploadError}</div>
              </CardContent>
            </Card>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={committing}>
              取消
            </Button>
            <Button onClick={handleCommit} disabled={committing || previewItems.length === 0}>
              {committing ? (
                <>
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  入库中
                </>
              ) : (
                '确认入库'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Step 3: 解析结果对话框 */}
      <Dialog open={resultOpen} onOpenChange={setResultOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>识别结果</DialogTitle>
            <DialogDescription>
              共解析 {results.length} 份文件
              {detectedClass != null && detectedGrade != null && (
                <>
                  ；检测到本班为{' '}
                  <span className="font-medium text-slate-700">
                    {formatClassLabel(detectedGrade, detectedClass)}
                  </span>
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">
            {results.map((r, i) => (
              <Card
                key={`${r.filename}-${i}`}
                className={cn(
                  r.parsed_ok ? 'border-success-500/40 bg-success-50/40' : 'border-danger-500/40 bg-danger-50/40'
                )}
              >
                <CardContent className="space-y-2 py-3">
                  <div className="flex items-start gap-2">
                    <FileSpreadsheet
                      className={cn(
                        'mt-0.5 h-4 w-4 shrink-0',
                        r.parsed_ok ? 'text-success-500' : 'text-danger-500'
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-800">
                        {r.filename}
                      </div>
                      {r.message && (
                        <div className="mt-0.5 text-xs text-slate-600">{r.message}</div>
                      )}
                    </div>
                    <Badge variant={r.parsed_ok ? 'success' : 'destructive'}>
                      {r.parsed_ok ? '解析成功' : '解析失败'}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 pl-6">
                    {r.kind && (
                      <Badge variant="secondary">
                        {KIND_LABEL[r.kind] ?? r.kind}
                      </Badge>
                    )}
                    {r.grade != null && (
                      <Badge variant="outline">{formatGradeLabel(r.grade)}</Badge>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
            {results.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
                没有返回任何结果
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setResultOpen(false)}>
              关闭
            </Button>
            <Button asChild>
              <Link href="/">查看仪表盘</Link>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
