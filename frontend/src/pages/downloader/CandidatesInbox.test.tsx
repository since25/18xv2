import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CandidatesInbox from './CandidatesInbox'
import FloatingActionBar from './FloatingActionBar'

const api = vi.hoisted(() => ({
  listInbox: vi.fn(),
  listDownloaderChannels: vi.fn(),
  ignoreChannel: vi.fn(),
  ignorePackages: vi.fn(),
  unignorePackages: vi.fn(),
  submitDownloaderBatches: vi.fn(),
  submitDownloaderPackages: vi.fn(),
  quickAddKeyword: vi.fn(),
}))

vi.mock('@/api/downloader', () => api)

const rows = [1, 2, 3].map((id) => ({
  package_id: id,
  remote_package_id: 100 + id,
  title: id === 1 ? '春季写真 001' : `资源包 ${id}`,
  channel_title: '频道 A',
  published_at: '2026-10-29T06:05:00Z',
  media_count: id === 1 ? 18 : 2,
  known_total_size: id === 1 ? 2.4 * 1024 ** 3 : 1000,
  current_download_status: id === 1 ? 'outdated' : 'never',
  index_revision: id === 1 ? 5 : 1,
  completed_revision: id === 1 ? 2 : null,
  new_media_count: id === 1 ? 3 : null,
  candidate_ids: id === 1 ? [11, 12] : [id + 11],
  keywords: id === 1 ? [{ keyword_entry_id: 7, keyword: '写真', matched_term: '写真' }, { keyword_entry_id: 8, keyword: '春季', matched_term: '春季' }] : [],
  ignored_at: null,
  ignored_reason: null,
}))

function inboxPayload(items: Array<Record<string, unknown>> = rows, page = 1) {
  return { items, total: items.length, page, page_size: 50, counts: { candidates: items.length, ignored: 1 } }
}

describe('CandidatesInbox', () => {
  afterEach(() => cleanup())

  beforeEach(() => {
    api.listInbox.mockResolvedValue(inboxPayload())
    api.listDownloaderChannels.mockResolvedValue(['频道 A', '频道 B'])
    api.ignorePackages.mockResolvedValue({ ignored: 1 })
    api.ignoreChannel.mockResolvedValue({ ignored: 3, package_ids: [1, 2, 3] })
    api.unignorePackages.mockResolvedValue({ restored: 1 })
    api.submitDownloaderBatches.mockResolvedValue({ submitted: 2, skipped: 0, failed: 0 })
    api.submitDownloaderPackages.mockResolvedValue({ submitted: 1, skipped: 0, failed: 0 })
  })

  it('shows channel errors and ignores a whole channel from the toolbar filter with undo', async () => {
    api.listInbox.mockResolvedValue(inboxPayload([
      { ...rows[0], current_download_status: 'failed', last_download_error: 'channel_unavailable', channel_error: 'channel_unavailable' },
    ]))
    render(<CandidatesInbox onCountsChange={vi.fn()} />)

    expect(await screen.findByText('频道不可访问')).toBeTruthy()
    expect(screen.getByText('频道不可访问（可能已被封禁或转为私有）')).toBeTruthy()
    // 行内不再放「忽略频道」
    expect(screen.queryByRole('button', { name: /忽略频道/ })).toBeNull()
    expect(screen.queryByRole('button', { name: '忽略此频道' })).toBeNull()

    fireEvent.mouseDown(screen.getByRole('combobox', { name: '频道筛选' }))
    await userEvent.click(await screen.findByTitle('频道 A'))
    await waitFor(() => expect(api.listInbox).toHaveBeenLastCalledWith(expect.objectContaining({ channelTitle: '频道 A' })))

    await userEvent.click(screen.getByRole('button', { name: '忽略此频道' }))
    await waitFor(() => expect(api.ignoreChannel).toHaveBeenCalledWith('频道 A'))
    expect(await screen.findByText('已忽略频道「频道 A」的 3 个资源包')).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: /撤\s*销/ }))
    await waitFor(() => expect(api.unignorePackages).toHaveBeenCalledWith([1, 2, 3]))
  })

  it('adds the search text to the blacklist after previewing the impact', async () => {
    api.quickAddKeyword.mockImplementation(async (keyword: string, listType: string, dryRun: boolean) => ({
      keyword, list_type: listType, entry_status: 'created', keyword_entry_id: dryRun ? null : 99,
      packages_affected: 1, candidates_created: 0, candidates_dismissed: 1, sample_titles: ['春季写真 001'],
    }))
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('资源包 2')

    await userEvent.type(screen.getByPlaceholderText('搜索资源包'), '写真')
    await userEvent.click(screen.getByRole('button', { name: '加入黑名单' }))

    await waitFor(() => expect(api.quickAddKeyword).toHaveBeenCalledWith('写真', 'blacklist', true))
    expect(await screen.findByText('涉及 1 个资源包，将移走 1 条待确认候选')).toBeTruthy()
    expect(screen.getAllByText('春季写真 001').length).toBeGreaterThan(1)

    const callsBefore = api.listInbox.mock.calls.length
    await userEvent.click(screen.getByRole('button', { name: '确认加入黑名单' }))
    await waitFor(() => expect(api.quickAddKeyword).toHaveBeenLastCalledWith('写真', 'blacklist', false))
    await waitFor(() => expect(api.listInbox.mock.calls.length).toBeGreaterThan(callsBefore))
  })

  it('hides the quick add buttons when search is empty', async () => {
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('资源包 2')
    expect(screen.queryByRole('button', { name: '加入黑名单' })).toBeNull()
    expect(screen.queryByRole('button', { name: '加入白名单' })).toBeNull()
  })

  it('shows the conflict message from the server', async () => {
    api.quickAddKeyword.mockRejectedValue(new Error('「写真」已在白名单中，请到关键词页修改类型'))
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('资源包 2')

    await userEvent.type(screen.getByPlaceholderText('搜索资源包'), '写真')
    await userEvent.click(screen.getByRole('button', { name: '加入黑名单' }))

    expect(await screen.findByText('「写真」已在白名单中，请到关键词页修改类型')).toBeTruthy()
    expect(screen.queryByRole('button', { name: '确认加入黑名单' })).toBeNull()
  })

  it('mounts the floating action bar outside the rendered page container', () => {
    const { container } = render(
      <FloatingActionBar
        count={1}
        totalBytes={1024}
        onSelectAll={vi.fn()}
        onClear={vi.fn()}
        onIgnore={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )

    const bar = screen.getByRole('status')
    expect(container.contains(bar)).toBe(false)
    expect(bar.parentElement).toBe(document.body)
  })

  it('renders a composite row with tags, size, media count and relative time', async () => {
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    expect(await screen.findByText('春季写真 001')).toBeInTheDocument()
    expect(screen.getByText(/#101/)).toBeInTheDocument()
    expect(screen.getByText('2.4 GB · 18 媒体')).toBeInTheDocument()
    expect(screen.getByText('有更新 (+3)')).toBeInTheDocument()
    expect(screen.getAllByText(/写真/).length).toBeGreaterThan(0)
  })

  it('downloads a single row from its inline button', async () => {
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('春季写真 001')
    await userEvent.click(screen.getByRole('button', { name: '下载 春季写真 001' }))
    await waitFor(() => expect(api.submitDownloaderBatches).toHaveBeenCalledWith([11, 12]))
  })

  it('downloads unmatched packages by package id', async () => {
    api.submitDownloaderBatches.mockClear()
    const unmatched = { ...rows[1], package_id: 9, title: '未命中资源包', candidate_ids: [], keywords: [], boundary_status: 'stable' }
    api.listInbox.mockImplementation(({ view }: { view: string }) =>
      Promise.resolve(view === 'unmatched' ? inboxPayload([unmatched]) : inboxPayload()),
    )
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('春季写真 001')
    await userEvent.click(screen.getByTitle(/未命中/))
    await userEvent.click(await screen.findByRole('button', { name: '下载 未命中资源包' }))
    await waitFor(() => expect(api.submitDownloaderPackages).toHaveBeenCalledWith([9]))
    expect(api.submitDownloaderBatches).not.toHaveBeenCalled()
  })

  it('submits all candidate ids for selected rows with Enter', async () => {
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('春季写真 001')
    const checkboxes = screen.getAllByRole('checkbox')
    await userEvent.click(checkboxes[1])
    await userEvent.click(checkboxes[2])
    expect(screen.getByText('已选 2 项')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Enter' })
    await waitFor(() => expect(api.submitDownloaderBatches).toHaveBeenCalledWith([11, 12, 13]))
  })

  it('supports shift selecting a range and slash focusing search', async () => {
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('春季写真 001')
    const checkboxes = screen.getAllByRole('checkbox')
    await userEvent.click(checkboxes[1])
    fireEvent.click(checkboxes[3], { shiftKey: true })
    expect(screen.getByText('已选 3 项')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: '/' })
    expect(screen.getByPlaceholderText('搜索资源包')).toHaveFocus()
  })

  it('restores an ignored row from the ignored segment', async () => {
    api.listInbox.mockImplementation(({ view }: { view: string }) =>
      Promise.resolve(view === 'ignored' ? inboxPayload([rows[0]]) : inboxPayload()),
    )
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('春季写真 001')
    await userEvent.click(screen.getByTitle('已忽略 (1)'))
    expect(await screen.findByRole('button', { name: '恢复' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '恢复' }))
    await waitFor(() => expect(api.unignorePackages).toHaveBeenCalledWith([1]))
  })

  it('reloads the first page after the last row is submitted and preserves selection on errors', async () => {
    api.submitDownloaderBatches.mockRejectedValueOnce(new Error('RN 不可达'))
    render(<CandidatesInbox onCountsChange={vi.fn()} />)
    await screen.findByText('春季写真 001')
    await userEvent.click(screen.getAllByRole('checkbox')[1])
    await userEvent.click(screen.getByRole('button', { name: /确认下载 1 个/ }))
    await waitFor(() => expect(screen.getByText('RN 不可达')).toBeInTheDocument())
    expect(screen.getAllByRole('checkbox')[1]).toBeChecked()
  })
})
