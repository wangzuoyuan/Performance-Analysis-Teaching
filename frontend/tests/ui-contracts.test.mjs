import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const dashboard = readFileSync(new URL('../src/app/page.tsx', import.meta.url), 'utf8')
const homework = readFileSync(new URL('../src/app/homework/page.tsx', import.meta.url), 'utf8')
const homeworkSettings = readFileSync(new URL('../src/app/homework/settings/page.tsx', import.meta.url), 'utf8')
const weeklyFocus = readFileSync(new URL('../src/components/WeeklyFocusCard.tsx', import.meta.url), 'utf8')

test('home dashboard renders a scope-aware homework overview', () => {
  assert.match(dashboard, /import HomeworkOverviewCard from ['"]@\/components\/HomeworkOverviewCard['"]/, '首页应导入作业看板摘要组件')
  assert.match(dashboard, /<HomeworkOverviewCard teachingClassId=\{tidParam \?\? undefined\} \/>/, '首页作业摘要必须跟随当前教学班范围')
})

test('weekly focus errors cannot crash the home dashboard', () => {
  assert.match(weeklyFocus, /if \(!r\.ok\) throw new Error/, '接口错误必须进入失败态')
  assert.match(weeklyFocus, /Array\.isArray\(\(payload as WeeklyFocus\)\.students\)/, '响应必须校验 students 数组')
})

test('homework registration page exposes its own class scope picker', () => {
  assert.match(homework, /import \{ ClassScopePicker \} from ['"]@\/components\/ClassScopePicker['"]/, '作业页应导入班级选择器')
  assert.match(homework, /<ClassScopePicker compact \/>/, '作业页头部应直接显示班级选择器，不能只依赖桌面顶栏')
})

test('homework dashboard ignores stale class-scope responses', () => {
  assert.match(homework, /const requestIdRef = useRef\(0\)/, '作业页应跟踪最新请求')
  assert.match(homework, /if \(requestId !== requestIdRef\.current\) return/, '旧班请求不得覆盖当前班数据')
  assert.match(homework, /setData\(null\)/, '切班或加载失败时应清空旧班数据')
})

test('homework dashboard hides business metrics on load error', () => {
  assert.match(homework, /\{!error && \(\s*<div className="grid grid-cols-2 gap-3 lg:grid-cols-4">/, '错误态不得继续显示四个零指标')
})

test('homework roster additions bind to the selected teaching class', () => {
  assert.match(homeworkSettings, /useClassScope\(\)/, '作业设置应读取当前教学班')
  assert.match(homeworkSettings, /teaching_class_id: current/, '新增花名册学生必须携带当前教学班')
  assert.match(homeworkSettings, /current === 'all'/, '全部范围不能新增无归属学生')
  assert.match(homeworkSettings, /const rosterRequestIdRef = useRef\(0\)/, '设置页应跟踪最新花名册请求')
  assert.match(homeworkSettings, /requestId !== rosterRequestIdRef\.current/, '旧班花名册响应不得覆盖当前班')
  assert.match(homeworkSettings, /const visibleRoster = rosterScope === current \? roster : \[\]/, '花名册必须只渲染与当前选择器一致的范围')
  assert.match(homeworkSettings, /setRoster\(\[\]\)/, '切班请求开始时应清空旧花名册')
  assert.match(homeworkSettings, /setRosterError\(true\)/, '花名册失败时应进入显式错误态')
  assert.match(homeworkSettings, /rosterScope !== current/, '花名册范围与选择器不一致时必须禁用新增')
})
