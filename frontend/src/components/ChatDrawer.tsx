'use client'

import { useEffect, useState, useRef, KeyboardEvent, PointerEvent } from 'react'
import { Bot, Send } from 'lucide-react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { cn } from '@/lib/utils'

interface Message {
  role: 'user' | 'assistant'
  content: string
  tool_calls?: any[]
}

const DEFAULT_DRAWER_WIDTH = 520
const MIN_DRAWER_WIDTH = 360
const MAX_DRAWER_WIDTH = 960
const PAGE_GUTTER = 96

function clampDrawerWidth(width: number) {
  if (typeof window === 'undefined') return width

  if (window.innerWidth < 640) return window.innerWidth

  const maxWidth = Math.max(
    MIN_DRAWER_WIDTH,
    Math.min(MAX_DRAWER_WIDTH, window.innerWidth - PAGE_GUTTER)
  )
  const minWidth = Math.min(MIN_DRAWER_WIDTH, maxWidth)
  return Math.min(Math.max(width, minWidth), maxWidth)
}

function visibleAssistantContent(content: string) {
  return content
    .split('\n')
    .filter(line => !line.trim().match(/^\[已查询：.+\]$/))
    .join('\n')
    .trim()
}

const markdownComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mb-2 mt-3 text-base font-semibold leading-snug text-slate-950 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-3 text-sm font-semibold leading-snug text-slate-950 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1.5 mt-3 text-sm font-semibold leading-snug text-slate-900 first:mt-0">
      {children}
    </h3>
  ),
  p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-slate-950">{children}</strong>,
  em: ({ children }) => <em className="text-slate-700">{children}</em>,
  ul: ({ children }) => (
    <ul className="my-2 list-disc space-y-1 pl-5 first:mt-0 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-2 list-decimal space-y-1 pl-5 first:mt-0 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-brand-500 pl-3 text-slate-700">
      {children}
    </blockquote>
  ),
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium text-brand-700 underline underline-offset-2"
    >
      {children}
    </a>
  ),
  code: ({ children, className }) => (
    <code
      className={cn(
        'rounded bg-slate-200 px-1 py-0.5 font-mono text-[0.8em] text-slate-900',
        className
      )}
    >
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="my-2 overflow-x-auto rounded-md bg-slate-900 p-3 text-xs leading-relaxed text-slate-50">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-md border border-slate-200 bg-white">
      <table className="min-w-full border-collapse text-left text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-slate-50 text-slate-700">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-slate-200 px-2 py-1.5 font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border-b border-slate-100 px-2 py-1.5">{children}</td>,
}

function buildPageContext() {
  if (typeof window === 'undefined') return {}

  const { pathname, href } = window.location
  const studentMatch = pathname.match(/^\/student\/([^/]+)/)
  const examMatch = pathname.match(/^\/exam\/([^/]+)/)

  return {
    page: { pathname, href },
    student_id: studentMatch ? decodeURIComponent(studentMatch[1]) : undefined,
    exam_id: examMatch ? Number(examMatch[1]) : undefined,
  }
}

export default function ChatDrawer() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [currentText, setCurrentText] = useState('')
  const [drawerWidth, setDrawerWidth] = useState(DEFAULT_DRAWER_WIDTH)
  const [isResizing, setIsResizing] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const resizeCleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const handler = () => setOpen(true)
    window.addEventListener('open-chat', handler)
    return () => window.removeEventListener('open-chat', handler)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentText])

  useEffect(() => {
    const handleResize = () => setDrawerWidth(width => clampDrawerWidth(width))
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    return () => resizeCleanupRef.current?.()
  }, [])

  const startResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (typeof window === 'undefined' || window.innerWidth < 640) return

    event.preventDefault()
    resizeCleanupRef.current?.()

    const startX = event.clientX
    const startWidth = drawerWidth
    const previousCursor = document.body.style.cursor
    const previousUserSelect = document.body.style.userSelect

    setIsResizing(true)
    document.body.style.cursor = 'ew-resize'
    document.body.style.userSelect = 'none'

    const handlePointerMove = (moveEvent: globalThis.PointerEvent) => {
      setDrawerWidth(clampDrawerWidth(startWidth + startX - moveEvent.clientX))
    }

    const cleanup = () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', cleanup)
      document.body.style.cursor = previousCursor
      document.body.style.userSelect = previousUserSelect
      setIsResizing(false)
      resizeCleanupRef.current = null
    }

    resizeCleanupRef.current = cleanup
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', cleanup, { once: true })
  }

  const sendMessage = async () => {
    if (!input.trim() || streaming) return

    const userMsg = { role: 'user' as const, content: input }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setStreaming(true)
    setCurrentText('')

    try {
      // 聊天是 SSE 流式、单条可达 60~120s。
      // - 生产（NAS）：同源相对路径 /api/chat，经 Caddy 直达后端，不缓冲、无超时；
      //   8000 端口不对外暴露，必须走同源。
      // - 本地 dev：直连后端 8000（跟随当前主机名），绕开 Next 开发代理的 ~30s 超时
      //   与 SSE 缓冲；想覆盖可设 NEXT_PUBLIC_CHAT_API_BASE。
      const explicit = process.env.NEXT_PUBLIC_CHAT_API_BASE
      const isDev = process.env.NODE_ENV !== 'production'
      const chatHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost'
      const chatBase = explicit ?? (isDev ? `http://${chatHost}:8000` : '')
      const res = await fetch(`${chatBase}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [...messages, userMsg], context: buildPageContext() }),
      })

      const reader = res.body?.getReader()
      if (!reader) return

      const decoder = new TextDecoder()
      let done = false
      let buffer = ''
      let assistantText = ''

      const processEvent = (eventText: string) => {
        const dataLine = eventText
          .split('\n')
          .find(line => line.startsWith('data:'))
        if (!dataLine) return
        try {
          const event = JSON.parse(dataLine.slice(5).trim())
          if (event.type === 'text') {
            assistantText += event.delta || ''
            setCurrentText(assistantText)
          }
        } catch {
          // Ignore malformed SSE frames.
        }
      }

      while (!done) {
        const { value, done: d } = await reader.read()
        done = d
        if (value) {
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split('\n\n')
          buffer = events.pop() || ''
          events.forEach(processEvent)
        }
      }
      if (buffer.trim()) processEvent(buffer)

      if (assistantText) {
        setMessages(prev => [...prev, { role: 'assistant', content: assistantText }])
        setCurrentText('')
      }
    } catch (err) {
      console.error(err)
    } finally {
      setStreaming(false)
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const renderBubble = (role: 'user' | 'assistant', content: string, key?: string | number) => {
    const isUser = role === 'user'
    const visibleContent = isUser ? content : visibleAssistantContent(content)
    if (!visibleContent) return null
    return (
      <div
        key={key}
        className={cn('flex w-full items-start gap-2', isUser ? 'justify-end' : 'justify-start')}
      >
        {!isUser && (
          <Avatar className="h-8 w-8 shrink-0">
            <AvatarFallback className="bg-brand-50 text-brand-600">
              <Bot className="h-4 w-4" />
            </AvatarFallback>
          </Avatar>
        )}
        <div
          className={cn(
            'min-w-0 break-words px-3 py-2 text-sm leading-relaxed shadow-sm',
            isUser
              ? 'max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-brand-600 text-white'
              : 'max-w-[calc(100%-2.5rem)] flex-1 rounded-2xl rounded-tl-sm bg-slate-100 text-slate-900'
          )}
        >
          {isUser ? (
            visibleContent
          ) : (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {visibleContent}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {isUser && (
          <Avatar className="h-8 w-8 shrink-0">
            <AvatarFallback className="bg-brand-600 text-white">我</AvatarFallback>
          </Avatar>
        )}
      </div>
    )
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent
        side="right"
        className="flex w-full max-w-none flex-col gap-0 p-0 sm:max-w-none"
        style={{ width: `min(100vw, ${drawerWidth}px)`, maxWidth: '100vw' }}
      >
        <button
          type="button"
          aria-label="调整对话助手宽度"
          onPointerDown={startResize}
          className={cn(
            'group absolute left-0 top-0 z-50 hidden h-full w-4 -translate-x-1/2 cursor-ew-resize items-center justify-center sm:flex',
            'focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-0',
            isResizing && 'bg-brand-500/10'
          )}
        >
          <span
            className={cn(
              'h-14 w-1 rounded-full bg-slate-300 transition-colors group-hover:bg-brand-500',
              isResizing && 'bg-brand-600'
            )}
          />
        </button>
        <SheetHeader className="border-b border-slate-200 px-5 py-4 text-left">
          <SheetTitle className="text-base font-semibold text-slate-900">
            AI 对话助手
          </SheetTitle>
          <SheetDescription className="text-xs text-slate-500">
            基于成绩数据回答你的问题
          </SheetDescription>
        </SheetHeader>

        <ScrollArea className="flex-1">
          <div className="space-y-4 px-5 py-4">
            {messages.length === 0 && !currentText && (
              <div className="flex h-full items-center justify-center py-10 text-center text-xs text-slate-400">
                还没有对话，输入问题开始吧。
              </div>
            )}
            {messages.map((m, i) => renderBubble(m.role, m.content, i))}
            {currentText && renderBubble('assistant', currentText, 'streaming')}
            <div ref={scrollRef} />
          </div>
        </ScrollArea>

        <div className="border-t border-slate-200 bg-white px-5 py-3">
          <div className="flex items-center gap-2">
            <Input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="问我任何关于成绩的问题..."
              disabled={streaming}
              className="flex-1 text-base"
            />
            <Button
              type="button"
              size="icon"
              onClick={sendMessage}
              disabled={streaming || !input.trim()}
              aria-label="发送"
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
