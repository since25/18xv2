import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import DownloaderPage from './DownloaderPage'

const api = vi.hoisted(() => ({
  getDownloaderStatus: vi.fn(),
  listInbox: vi.fn(),
  getDownloaderSummary: vi.fn(),
  listTasks: vi.fn(),
  syncDownloaderPackages: vi.fn(),
  syncDownloaderTasks: vi.fn(),
  controlDownloader: vi.fn(),
  submitDownloaderBatches: vi.fn(),
  ignorePackages: vi.fn(),
  unignorePackages: vi.fn(),
  cancelDownloaderTask: vi.fn(),
  retryDownloaderTask: vi.fn(),
  listDownloaderChannels: vi.fn(),
  listDownloaderKeywords: vi.fn(),
  getTaskDetail: vi.fn(),
}))

vi.mock('@/api/downloader', () => api)

function renderPage(initialEntry = '/downloader') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <DownloaderPage />
      <LocationProbe />
    </MemoryRouter>,
  )
}

function LocationProbe() {
  const location = useLocation()
  return <span data-testid="location-search">{location.search}</span>
}

describe('DownloaderPage', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  beforeEach(() => {
    api.getDownloaderStatus.mockResolvedValue({ enabled: false, remote_ready: false, latest_sync: null })
    api.listInbox.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, counts: { candidates: 0, ignored: 0 } })
    api.getDownloaderSummary.mockResolvedValue({ active_count: 0 })
    api.listTasks.mockResolvedValue({ items: [], total: 0 })
    api.syncDownloaderPackages.mockResolvedValue({ packages_seen: 0, candidates_created: 0 })
    api.syncDownloaderTasks.mockResolvedValue({ tasks_seen: 0, tasks_updated: 0 })
    api.controlDownloader.mockResolvedValue({})
    api.submitDownloaderBatches.mockResolvedValue({ submitted: 0, skipped: 0, failed: 0 })
    api.ignorePackages.mockResolvedValue({ ignored: 0 })
    api.unignorePackages.mockResolvedValue({ restored: 0 })
    api.cancelDownloaderTask.mockResolvedValue({})
    api.retryDownloaderTask.mockResolvedValue({})
    api.listDownloaderChannels.mockResolvedValue([])
    api.listDownloaderKeywords.mockResolvedValue([])
  })

  it('renders the downloader title and disabled state', async () => {
    renderPage()
    expect(screen.getByRole('heading', { name: '下载器' })).toBeInTheDocument()
    expect(await screen.findByText('RN 下载器未启用')).toBeInTheDocument()
  })

  it('defaults to the inbox and switches to tasks through the URL', async () => {
    renderPage()
    expect(await screen.findByTestId('candidates-inbox')).toBeInTheDocument()
    const tasksTab = screen.getByTitle('任务看板与历史 (0 活跃)')
    fireEvent.click(tasksTab)
    expect(await screen.findByTestId('tasks-board')).toBeInTheDocument()
  })

  it('opens directly on the task board from the view query', async () => {
    renderPage('/downloader?view=tasks')
    expect(await screen.findByTestId('tasks-board')).toBeInTheDocument()
  })

  it('restores and closes a task inspector through the task query', async () => {
    api.getTaskDetail.mockResolvedValue({
      task: { title: '任务资源', status: 'completed', duration_seconds: 60, downloaded_bytes: 10, total_bytes: 10, package_title: '资源包', channel_title: '频道 A' },
      files: [],
      failed_files: [],
      history: [],
    })
    renderPage('/downloader?view=tasks&task=task-1')
    expect(await screen.findByText('任务资源')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent('view=tasks'))
    expect(screen.getByTestId('location-search')).not.toHaveTextContent('task=task-1')
  })
})
