import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ReviewIntakeItem,
  ReviewIntakeListResponse,
  ReviewIntakeSummary,
} from '@/api/reviewIntake'

const listReviewIntakeItems = vi.fn()
const getReviewIntakeSummary = vi.fn()
const batchApproveReviewIntakeItems = vi.fn()
const batchDismissReviewIntakeItems = vi.fn()
const batchDeleteReviewIntakeItems = vi.fn()
const createIgnoreKeyword = vi.fn()
const createReviewIntakeItem = vi.fn()
const restoreReviewIntakeItem = vi.fn()

vi.mock('@/api/reviewIntake', () => ({
  listReviewIntakeItems: (...args: unknown[]) => listReviewIntakeItems(...args),
  getReviewIntakeSummary: (...args: unknown[]) => getReviewIntakeSummary(...args),
  batchApproveReviewIntakeItems: (...args: unknown[]) => batchApproveReviewIntakeItems(...args),
  batchDismissReviewIntakeItems: (...args: unknown[]) => batchDismissReviewIntakeItems(...args),
  batchDeleteReviewIntakeItems: (...args: unknown[]) => batchDeleteReviewIntakeItems(...args),
  createIgnoreKeyword: (...args: unknown[]) => createIgnoreKeyword(...args),
  createReviewIntakeItem: (...args: unknown[]) => createReviewIntakeItem(...args),
  restoreReviewIntakeItem: (...args: unknown[]) => restoreReviewIntakeItem(...args),
}))

const { default: ReviewIntakePage } = await import('./ReviewIntakePage')

function makeItem(overrides: Partial<ReviewIntakeItem> & { id: number }): ReviewIntakeItem {
  return {
    bucket: 'whitelist',
    raw_path: `/Volumes/finish/作品${overrides.id}.mp4`,
    normalized_path: '',
    path_hash: `hash-${overrides.id}`,
    source: 'shortcut',
    note: null,
    keyword_candidates: [],
    status: 'pending',
    approved_keyword_entry_id: null,
    approved_keyword: null,
    reviewed_at: null,
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
    ...overrides,
  }
}

const WHITE_ITEMS: ReviewIntakeItem[] = [
  makeItem({
    id: 1,
    raw_path: '/Volumes/finish/抖音合集/姝姬娘娘 舞蹈.mp4',
    keyword_candidates: [
      { keyword: '姝姬娘娘', count: 1, source: 'segment', examples: [], match_status: 'new', matched_entry_id: null, matched_canonical_name: null, matched_keyword_type: null, similar_score: null },
      { keyword: '舞蹈', count: 1, source: 'segment', examples: [], match_status: 'new', matched_entry_id: null, matched_canonical_name: null, matched_keyword_type: null, similar_score: null },
    ],
  }),
  makeItem({
    id: 2,
    raw_path: '/Volumes/finish/小仙女下午茶.mp4',
    keyword_candidates: [
      { keyword: '小仙女下午茶', count: 1, source: 'bracket', examples: [], match_status: 'new', matched_entry_id: null, matched_canonical_name: null, matched_keyword_type: null, similar_score: null },
    ],
  }),
]

const BLACK_ITEMS: ReviewIntakeItem[] = [
  makeItem({ id: 3, bucket: 'blacklist', raw_path: '/Volumes/finish/广告推广.mp4' }),
]

const SUMMARY: ReviewIntakeSummary = {
  whitelist_pending: 2,
  blacklist_pending: 1,
  whitelist_approved: 0,
  blacklist_approved: 0,
  whitelist_dismissed: 0,
  blacklist_dismissed: 0,
}

function listResponse(items: ReviewIntakeItem[]): ReviewIntakeListResponse {
  return { items, total: items.length, page: 1, page_size: 200 }
}

async function renderPage() {
  render(<ReviewIntakePage />)
  await screen.findByText('/Volumes/finish/抖音合集/姝姬娘娘 舞蹈.mp4')
}

function keywordInputs() {
  return screen.getAllByPlaceholderText('白名单词') as HTMLInputElement[]
}

beforeEach(() => {
  vi.clearAllMocks()
  listReviewIntakeItems.mockImplementation((params: { bucket: string }) =>
    Promise.resolve(listResponse(params.bucket === 'whitelist' ? WHITE_ITEMS : BLACK_ITEMS)),
  )
  getReviewIntakeSummary.mockResolvedValue(SUMMARY)
})

// 仓库没有开 vitest globals，RTL 的自动清理不会生效，必须手动卸载上一个用例的 DOM
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ReviewIntakePage', () => {
  it('点候选词会填入关键词并自动勾选该行', async () => {
    await renderPage()

    fireEvent.click(screen.getByText('姝姬娘娘'))

    expect(keywordInputs()[0].value).toBe('姝姬娘娘')
    expect(await screen.findByText(/已选 1 条 · 其中 1 条已填关键词/)).toBeInTheDocument()
  })

  it('Shift+点击候选词是追加而不是替换', async () => {
    await renderPage()

    fireEvent.click(screen.getByText('姝姬娘娘'))
    fireEvent.click(screen.getByText('舞蹈'), { shiftKey: true })

    expect(keywordInputs()[0].value).toBe('姝姬娘娘舞蹈')
  })

  it('在路径上划词可以直接填入关键词', async () => {
    await renderPage()

    vi.spyOn(window, 'getSelection').mockReturnValue({
      toString: () => ' 抖音合集/ ',
    } as unknown as Selection)

    fireEvent.mouseUp(screen.getByTestId('review-path-1'))

    expect(keywordInputs()[0].value).toBe('抖音合集')
  })

  it('批量批准后成功行移出列表，失败行留在原地并显示原因', async () => {
    batchApproveReviewIntakeItems.mockResolvedValue({
      succeeded: 1,
      failed: 1,
      results: [
        { id: 1, ok: true, item: null, error: null },
        { id: 2, ok: false, item: null, error: '关键词已存在于 blacklist，不能直接归入 whitelist' },
      ],
    })
    await renderPage()

    fireEvent.click(screen.getByText('姝姬娘娘'))
    fireEvent.click(screen.getByText('小仙女下午茶'))
    fireEvent.click(screen.getByRole('button', { name: '批量批准' }))

    const confirmButton = await screen.findByRole('button', { name: '确认批准' })
    fireEvent.click(confirmButton)

    await waitFor(() => {
      expect(batchApproveReviewIntakeItems).toHaveBeenCalledWith([
        { id: 1, keyword: '姝姬娘娘' },
        { id: 2, keyword: '小仙女下午茶' },
      ])
    })
    await waitFor(() => {
      expect(screen.queryByText('/Volumes/finish/抖音合集/姝姬娘娘 舞蹈.mp4')).not.toBeInTheDocument()
    })
    expect(
      screen.getByText(/关键词已存在于 blacklist，不能直接归入 whitelist/),
    ).toBeInTheDocument()
    // 列表不再整页重拉，只刷新顶部统计
    expect(listReviewIntakeItems).toHaveBeenCalledTimes(2)
  })

  it('编辑弹层可以从完整路径里改出关键词', async () => {
    await renderPage()

    fireEvent.click(screen.getByRole('button', { name: '编辑关键词 1' }))
    const editor = await screen.findByDisplayValue('/Volumes/finish/抖音合集/姝姬娘娘 舞蹈.mp4')
    fireEvent.change(editor, { target: { value: '姝姬娘娘' } })
    fireEvent.click(screen.getByRole('button', { name: '确 认' }))

    await waitFor(() => expect(keywordInputs()[0].value).toBe('姝姬娘娘'))
  })

  it('切到黑名单 Tab 只显示黑名单待审记录', async () => {
    await renderPage()

    fireEvent.click(screen.getByRole('tab', { name: '黑名单待审 1' }))

    const blackPanel = await screen.findByText('/Volumes/finish/广告推广.mp4')
    expect(blackPanel).toBeInTheDocument()
  })

  it('批量忽略只提交当前 Tab 里选中的行', async () => {
    batchDismissReviewIntakeItems.mockResolvedValue({
      succeeded: 1,
      failed: 0,
      results: [{ id: 1, ok: true, item: null, error: null }],
    })
    await renderPage()

    fireEvent.click(screen.getByText('姝姬娘娘'))
    fireEvent.click(screen.getByRole('button', { name: '批量忽略' }))

    await waitFor(() => expect(batchDismissReviewIntakeItems).toHaveBeenCalledWith([1]))
  })

  it('批量加入忽略库只列出选中行里的可忽略候选词', async () => {
    createIgnoreKeyword.mockResolvedValue({ id: 9 })
    await renderPage()

    fireEvent.click(screen.getByText('姝姬娘娘'))
    fireEvent.click(screen.getByRole('button', { name: '批量加入忽略库' }))

    const title = await screen.findByText('选择要加入忽略库的词')
    const dialog = title.closest('.ant-modal-header')?.parentElement as HTMLElement
    expect(within(dialog).getByText('舞蹈')).toBeInTheDocument()
    expect(within(dialog).queryByText('小仙女下午茶')).not.toBeInTheDocument()

    fireEvent.click(within(dialog).getByText('舞蹈'))
    fireEvent.click(within(dialog).getByRole('button', { name: '加入忽略库' }))

    await waitFor(() => expect(createIgnoreKeyword).toHaveBeenCalledWith('舞蹈'))
  })
})
