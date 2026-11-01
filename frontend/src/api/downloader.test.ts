import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ignorePackages,
  listTasks,
} from './downloader'

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('./client', () => ({
  api: { get, post },
}))

describe('downloader API', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    get.mockResolvedValue({})
    post.mockResolvedValue({})
  })

  it('serializes task filters into the backend query contract', async () => {
    await listTasks({
      status: ['active', 'failed'],
      since: '2026-10-25T00:00:00+08:00',
      page: 2,
    })

    expect(get).toHaveBeenCalledWith(
      '/downloader/tasks?status=active%2Cfailed&since=2026-10-25T00%3A00%3A00%2B08%3A00&page=2&page_size=20',
    )
  })

  it('posts candidate ids when ignoring packages', async () => {
    await ignorePackages({ candidateIds: [1, 2] })

    expect(post).toHaveBeenCalledWith('/downloader/packages/ignore', { candidate_ids: [1, 2] })
  })
})
