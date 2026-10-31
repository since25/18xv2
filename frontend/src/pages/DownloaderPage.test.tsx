import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import DownloaderPage from './DownloaderPage'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('@/api/client', () => ({
  api: { get, post },
}))

describe('DownloaderPage', () => {
  beforeEach(() => {
    get.mockImplementation((path: string) => {
      if (path.startsWith('/downloader/packages')) return Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 })
      if (path.startsWith('/downloader/tasks')) return Promise.resolve({ items: [], total: 0 })
      return Promise.resolve({ enabled: false, remote_ready: false, latest_sync: null })
    })
    post.mockResolvedValue({})
  })

  it('renders the whitelist package workbench and disabled state', async () => {
    render(<DownloaderPage />)
    expect(screen.getByRole('heading', { name: '下载器资源包' })).toBeInTheDocument()
    expect(await screen.findByText('RN 下载器未启用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /同步资源包/ })).toBeInTheDocument()
  })
})
