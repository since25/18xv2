import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
const whitelist = vi.hoisted(() => Object.fromEntries([
  'bulkDismissCandidates', 'dismissCandidate', 'getActiveJobs', 'listCandidates', 'restoreCandidate',
  'startScanJob', 'startSubmitJob', 'subscribeJobProgress',
].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>)
const review = vi.hoisted(() => Object.fromEntries([
  'batchApproveReviewIntakeItems', 'batchDeleteReviewIntakeItems', 'batchDismissReviewIntakeItems',
  'createIgnoreKeyword', 'createReviewIntakeItem', 'getReviewIntakeSummary', 'listReviewIntakeItems', 'restoreReviewIntakeItem',
].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>)
const emby = vi.hoisted(() => Object.fromEntries([
  'applyEmbyMetadataCandidate', 'confirmEmbyDeletePlan', 'createEmbyDeletePlanForScope', 'deleteEmbyDeletePlan',
  'deleteEmbyMetadataCandidate', 'getEmbyDeletePlan', 'getEmbyMetadataCandidate', 'listEmbyDeletePlans', 'listEmbyMetadataCandidates',
].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>)
const dedupe = vi.hoisted(() => Object.fromEntries([
  'createDedupeDeletePlan', 'getDedupeActiveJobs', 'getDedupeGroup', 'listDedupeDeletePlans', 'listDedupeGroups',
  'reviewDedupeGroup', 'startDedupeConfirmJob', 'startDedupeDeleteJob', 'startDedupeScanJob', 'subscribeDedupeJob',
].map((name) => [name, vi.fn()])) as Record<string, ReturnType<typeof vi.fn>>)

vi.mock('@/api/client', () => ({ api }))
vi.mock('../api/client', () => ({ api }))
vi.mock('@/api/whitelistBatch', () => whitelist)
vi.mock('@/api/reviewIntake', () => review)
vi.mock('@/api/embyMediaActions', () => emby)
vi.mock('../api/dedupe', () => dedupe)

import OrganizeTasksPage from './OrganizeTasksPage'
import PlansPage from './PlansPage'
import PlanDetailPage from './PlanDetailPage'
import ExecutorPage from './ExecutorPage'
import WhitelistBatchPage from './WhitelistBatchPage'
import ReviewIntakePage from './ReviewIntakePage'
import EmbyMediaActionsPage from './EmbyMediaActionsPage'
import FileDedupePage from './FileDedupePage'
import MagnetTasksPage from './MagnetTasksPage'

function renderPage(page: ReactNode, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/plans/:id" element={page} />
        <Route path="*" element={page} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('流程组页面冒烟渲染', () => {
  beforeEach(() => {
    const empty = { items: [], total: 0, records: [], jobs: [], plans: [], errors: [] }
    api.get.mockImplementation((path: string) => {
      if (path === '/plans/1') {
        return Promise.resolve({ id: 1, strategy_version: 'v1', dry_run: false, items: [] })
      }
      return Promise.resolve(empty)
    })
    api.post.mockResolvedValue(empty)
    api.patch.mockResolvedValue(empty)
    api.delete.mockResolvedValue(empty)
    for (const fn of Object.values(whitelist)) fn.mockResolvedValue({ items: [], total: 0, jobs: [] })
    review.listReviewIntakeItems.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 })
    review.getReviewIntakeSummary.mockResolvedValue({ whitelist_pending: 0, blacklist_pending: 0, keyword_pending: 0, whitelist_approved: 0, blacklist_approved: 0, keyword_approved: 0, whitelist_dismissed: 0, blacklist_dismissed: 0, keyword_dismissed: 0 })
    for (const fn of Object.values(review)) if (fn !== review.listReviewIntakeItems && fn !== review.getReviewIntakeSummary) fn.mockResolvedValue({})
    emby.listEmbyDeletePlans.mockResolvedValue([])
    emby.listEmbyMetadataCandidates.mockResolvedValue([])
    for (const fn of Object.values(emby)) if (fn !== emby.listEmbyDeletePlans && fn !== emby.listEmbyMetadataCandidates) fn.mockResolvedValue({})
    dedupe.listDedupeGroups.mockResolvedValue({ items: [], total: 0 })
    dedupe.listDedupeDeletePlans.mockResolvedValue({ items: [] })
    dedupe.getDedupeActiveJobs.mockResolvedValue([])
    for (const fn of Object.values(dedupe)) if (fn !== dedupe.listDedupeGroups && fn !== dedupe.listDedupeDeletePlans && fn !== dedupe.getDedupeActiveJobs) fn.mockResolvedValue({})
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  const cases: Array<[string, ReactNode, string, string?]> = [
    ['整理任务', <OrganizeTasksPage />, '整理任务'],
    ['整理计划', <PlansPage />, '整理计划'],
    ['计划详情', <PlanDetailPage />, '计划 #1 详情', '/plans/1'],
    ['执行日志', <ExecutorPage />, '执行日志'],
    ['白名单批处理', <WhitelistBatchPage />, '白名单批处理'],
    ['待审核', <ReviewIntakePage />, '待审核'],
    ['Emby 媒体动作', <EmbyMediaActionsPage />, 'Emby 媒体动作'],
    ['文件去重', <FileDedupePage />, '文件去重'],
    ['磁力下载台', <MagnetTasksPage />, '磁力下载台'],
  ]

  it.each(cases)('渲染 %s 的 PageScaffold 标题', async (_name, page, title, path) => {
    renderPage(page, path)
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
  })
})
