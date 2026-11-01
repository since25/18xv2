import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CandidatesInbox from './CandidatesInbox'
import FloatingActionBar from './FloatingActionBar'

const api = vi.hoisted(() => ({
  listInbox: vi.fn(),
  ignorePackages: vi.fn(),
  unignorePackages: vi.fn(),
  submitDownloaderBatches: vi.fn(),
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

function inboxPayload(items = rows, page = 1) {
  return { items, total: items.length, page, page_size: 50, counts: { candidates: items.length, ignored: 1 } }
}

describe('CandidatesInbox', () => {
  afterEach(() => cleanup())

  beforeEach(() => {
    api.listInbox.mockResolvedValue(inboxPayload())
    api.ignorePackages.mockResolvedValue({ ignored: 1 })
    api.unignorePackages.mockResolvedValue({ restored: 1 })
    api.submitDownloaderBatches.mockResolvedValue({ submitted: 2, skipped: 0, failed: 0 })
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
