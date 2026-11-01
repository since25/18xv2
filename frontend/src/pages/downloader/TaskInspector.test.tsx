import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TaskInspector from './TaskInspector'

const api = vi.hoisted(() => ({ getTaskDetail: vi.fn(), retryDownloaderTask: vi.fn() }))
vi.mock('@/api/downloader', () => api)

const detail = {
  task: {
    id: 1, remote_task_id: 'task-1', source: 'rn', task_type: 'download', title: '春季写真全集', status: 'completed_with_errors', total_count: 3, success_count: 2, failed_count: 1, current_file: null, observed_at: null, remote_created_at: '2026-11-01T00:00:00Z', remote_updated_at: null, finished_at: '2026-11-01T01:00:00Z', total_bytes: 300, downloaded_bytes: 200, channel_title: '频道 A', duration_seconds: 754, download_speed_bytes: 0, package_id: 1, package_title: '春季写真全集',
  },
  files: [
    { message_id: '1', filename: '001.jpg', status: 'completed', total_size: 100, downloaded_size: 100, error: null },
    { message_id: '2', filename: '002.jpg', status: 'downloaded', total_size: 100, downloaded_size: 100, error: null },
    { message_id: '3', filename: '003.jpg', status: 'download_failed', total_size: 100, downloaded_size: 0, error: 'Connection reset by peer' },
  ],
  failed_files: [{ message_id: '3', filename: '003.jpg', status: 'download_failed', total_size: 100, downloaded_size: 0, error: 'Connection reset by peer' }],
  history: [],
}

describe('TaskInspector', () => {
  beforeEach(() => {
    api.getTaskDetail.mockResolvedValue(detail)
    api.retryDownloaderTask.mockResolvedValue({})
  })
  afterEach(() => { cleanup(); vi.clearAllMocks() })

  it('loads the detail and highlights failed files', async () => {
    render(<TaskInspector taskId="task-1" onClose={vi.fn()} onChanged={vi.fn()} />)
    expect((await screen.findAllByText('003.jpg')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Connection reset by peer').length).toBeGreaterThan(0)
  })

  it('retries all failed files and notifies the parent', async () => {
    const onChanged = vi.fn()
    render(<TaskInspector taskId="task-1" onClose={vi.fn()} onChanged={onChanged} />)
    await screen.findAllByText('003.jpg')
    fireEvent.click(screen.getByRole('button', { name: '重试全部失败文件' }))
    await waitFor(() => expect(api.retryDownloaderTask).toHaveBeenCalledWith('task-1', { onlyFailed: true }))
    expect(onChanged).toHaveBeenCalled()
  })

  it('closes with Escape and filters files by status and filename', async () => {
    const onClose = vi.fn()
    render(<TaskInspector taskId="task-1" onClose={onClose} onChanged={vi.fn()} />)
    await screen.findAllByText('003.jpg')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
    fireEvent.click(screen.getByTitle('仅失败'))
    expect(screen.queryByText('001.jpg')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTitle('全部'))
    fireEvent.change(screen.getByPlaceholderText('搜索文件名'), { target: { value: '001' } })
    const fileTable = screen.getByText('文件清单（共 3 个）').closest('.task-inspector-files')
    expect(fileTable).not.toBeNull()
    expect(fileTable).toHaveTextContent('001.jpg')
    expect(fileTable).not.toHaveTextContent('003.jpg')
  })

  it('does not show failed section when there are no failed files', async () => {
    api.getTaskDetail.mockResolvedValue({ ...detail, failed_files: [], files: detail.files.slice(0, 2), task: { ...detail.task, failed_count: 0, status: 'completed' } })
    render(<TaskInspector taskId="task-1" onClose={vi.fn()} onChanged={vi.fn()} />)
    await screen.findAllByText('001.jpg')
    expect(screen.queryByText('重试全部失败文件')).not.toBeInTheDocument()
  })
})
