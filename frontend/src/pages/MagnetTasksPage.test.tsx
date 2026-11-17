import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))

vi.mock('@/api/client', () => ({ api }))
vi.mock('../api/client', () => ({ api }))

import MagnetTasksPage from './MagnetTasksPage'

describe('MagnetTasksPage 拉取目录树快照', () => {
  beforeEach(() => {
    api.get.mockImplementation((path: string) => Promise.resolve(
      path.startsWith('/imports/data') ? { total: 0, items: [] } : { batches: [] },
    ))
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('成功提示使用后端返回的 import_id', async () => {
    // 后端 POST /imports/remote-fetch 返回 {import_id, status}，没有 id 字段
    api.post.mockResolvedValue({ import_id: 42, status: 'pending' })
    render(<MemoryRouter><MagnetTasksPage /></MemoryRouter>)

    fireEvent.click(await screen.findByText('目录树去重设置（本地匹配，无 API 风控）'))
    fireEvent.change(await screen.findByPlaceholderText('115 目录 CID'), { target: { value: '123' } })
    fireEvent.click(screen.getByRole('button', { name: /拉取目录树快照/ }))

    expect(await screen.findByText('目录树快照已创建，批次 #42')).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/imports/remote-fetch', expect.objectContaining({ cid: '123' }))
  })
})
