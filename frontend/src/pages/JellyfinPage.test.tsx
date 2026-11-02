import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { JellyfinStatus } from '@/api/jellyfin'

const getJellyfinStatus = vi.fn()
const startJellyfinScan = vi.fn()
const startJellyfinSync = vi.fn()
const getJellyfinJob = vi.fn()
const listJellyfinUnmatched = vi.fn()
const listJellyfinConflicts = vi.fn()

vi.mock('@/api/jellyfin', () => ({
  getJellyfinStatus: (...args: unknown[]) => getJellyfinStatus(...args),
  startJellyfinScan: (...args: unknown[]) => startJellyfinScan(...args),
  startJellyfinSync: (...args: unknown[]) => startJellyfinSync(...args),
  getJellyfinJob: (...args: unknown[]) => getJellyfinJob(...args),
  listJellyfinUnmatched: (...args: unknown[]) => listJellyfinUnmatched(...args),
  listJellyfinConflicts: (...args: unknown[]) => listJellyfinConflicts(...args),
}))

const { default: JellyfinPage } = await import('./JellyfinPage')

function makeStatus(overrides: Partial<JellyfinStatus> = {}): JellyfinStatus {
  return {
    scan_enabled: true,
    sync_enabled: true,
    local_roots: ['/media/已整理'],
    strm_roots: ['/media/strm'],
    latest_scan: null,
    latest_sync: null,
    counts: { active_items: 120, matched: 100, unmatched: 15, nfo_error: 5, pending_resolve: 7 },
    collections: { active: 30, conflict: 1, retired: 0 },
    ...overrides,
  }
}

function buttonByText(text: string) {
  return screen.getByText(text).closest('button') as HTMLButtonElement
}

describe('JellyfinPage', () => {
  beforeEach(() => {
    getJellyfinStatus.mockResolvedValue(makeStatus())
    listJellyfinUnmatched.mockResolvedValue({
      total: 1,
      items: [{ id: 1, source: 'local', path: '/media/已整理/未知目录/a.mp4', match_state: 'unmatched', match_note: null }],
    })
    listJellyfinConflicts.mockResolvedValue({ items: [] })
    startJellyfinScan.mockResolvedValue({ job_id: 'job-1' })
    getJellyfinJob.mockResolvedValue({ job_id: 'job-1', done: false })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('未启用时两个按钮都禁用', async () => {
    getJellyfinStatus.mockResolvedValue(makeStatus({ scan_enabled: false, sync_enabled: false }))
    render(<JellyfinPage />)
    await waitFor(() => expect(getJellyfinStatus).toHaveBeenCalled())
    await waitFor(() => expect(buttonByText('立即扫描')).toBeDisabled())
    expect(buttonByText('立即同步合集')).toBeDisabled()
  })

  it('渲染计数与未匹配列表', async () => {
    render(<JellyfinPage />)
    expect(await screen.findByText('待 Jellyfin 扫描')).toBeInTheDocument()
    expect(screen.getByText('120')).toBeInTheDocument()
    expect(await screen.findByText('/media/已整理/未知目录/a.mp4')).toBeInTheDocument()
  })

  it('点击扫描会调用扫描接口', async () => {
    render(<JellyfinPage />)
    await waitFor(() => expect(buttonByText('立即扫描')).not.toBeDisabled())
    fireEvent.click(buttonByText('立即扫描'))
    await waitFor(() => expect(startJellyfinScan).toHaveBeenCalledTimes(1))
  })

  it('按来源筛选时带上 source 参数', async () => {
    render(<JellyfinPage />)
    await waitFor(() => expect(listJellyfinUnmatched).toHaveBeenCalled())
    fireEvent.mouseDown(screen.getByLabelText('来源筛选'))
    fireEvent.click(await screen.findByText('115 STRM', { selector: '.ant-select-item-option-content' }))
    await waitFor(() =>
      expect(listJellyfinUnmatched).toHaveBeenLastCalledWith(expect.objectContaining({ source: 'strm_115', offset: 0 })),
    )
  })
})
