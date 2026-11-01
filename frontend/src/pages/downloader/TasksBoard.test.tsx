import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TasksBoard from './TasksBoard'

const api = vi.hoisted(() => ({
  listTasks: vi.fn(),
  getDownloaderSummary: vi.fn(),
  listDownloaderChannels: vi.fn(),
  listDownloaderKeywords: vi.fn(),
  cancelDownloaderTask: vi.fn(),
  retryDownloaderTask: vi.fn(),
}))

vi.mock('@/api/downloader', () => api)

const task = {
  id: 1,
  remote_task_id: 'task-1',
  source: 'rn',
  task_type: 'download',
  title: '春季写真全集',
  status: 'completed_with_errors',
  total_count: 10,
  success_count: 8,
  failed_count: 2,
  current_file: null,
  observed_at: '2026-11-01T04:00:00Z',
  remote_created_at: '2026-10-31T04:00:00Z',
  remote_updated_at: '2026-11-01T04:00:00Z',
  finished_at: '2026-11-01T04:00:00Z',
  total_bytes: 8.2 * 1024 ** 3,
  downloaded_bytes: 7.8 * 1024 ** 3,
  channel_title: '频道 A',
  duration_seconds: 754,
  download_speed_bytes: 0,
  package_id: 1,
  package_title: '春季写真全集',
}

function renderBoard(initial = '/downloader?view=tasks') {
  return render(<MemoryRouter initialEntries={[initial]}><TasksBoard onActiveCountChange={vi.fn()} onOpenTask={vi.fn()} /></MemoryRouter>)
}

describe('TasksBoard', () => {
  beforeEach(() => {
    api.listTasks.mockResolvedValue({ items: [task], total: 1 })
    api.getDownloaderSummary.mockResolvedValue({ today_count: 2, today_bytes: 300, week_count: 4, week_bytes: 1000, active_count: 0, week_failed_files: 2 })
    api.listDownloaderChannels.mockResolvedValue(['频道 A'])
    api.listDownloaderKeywords.mockResolvedValue([{ id: 7, canonical_name: '写真' }])
    api.cancelDownloaderTask.mockResolvedValue({})
    api.retryDownloaderTask.mockResolvedValue({})
  })

  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('passes failed and seven day filters to the task API', async () => {
    renderBoard()
    await screen.findByText('春季写真全集')
    fireEvent.click(screen.getByTitle('失败'))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '时间范围' }))
    fireEvent.click((await screen.findAllByText('近 7 天'))[1])
    await waitFor(() => expect(api.listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ status: ['failed'], since: expect.stringContaining('T00:00:00+08:00') })))
  })

  it('renders status, transfer size and duration', async () => {
    renderBoard()
    expect(await screen.findByText('部分完成', { selector: '.status-tag' })).toBeInTheDocument()
    expect(screen.getByText('7.8 GB / 8.2 GB')).toBeInTheDocument()
    expect(screen.getByText('12 分 34 秒', { selector: '.downloader-duration-value' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '启动与耗时' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '启动时间' })).not.toBeInTheDocument()
  })

  it('opens a task when the row is clicked but stops propagation for cancel', async () => {
    const onOpenTask = vi.fn()
    api.listTasks.mockResolvedValueOnce({ items: [{ ...task, status: 'downloading' }], total: 1 })
    render(<MemoryRouter initialEntries={['/downloader?view=tasks']}><TasksBoard onActiveCountChange={vi.fn()} onOpenTask={onOpenTask} /></MemoryRouter>)
    const title = (await screen.findAllByText('春季写真全集'))[1]
    fireEvent.click(title)
    expect(onOpenTask).toHaveBeenCalledWith('task-1')
    onOpenTask.mockClear()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(onOpenTask).not.toHaveBeenCalled()
  })

  it('keeps rows with missing remote creation time visible', async () => {
    api.listTasks.mockResolvedValueOnce({ items: [{ ...task, remote_created_at: null }], total: 1 })
    renderBoard()
    expect((await screen.findAllByText('-')).length).toBeGreaterThan(0)
  })
})
