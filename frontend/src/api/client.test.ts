import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, setUnauthorizedHandler } from './client'

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('api client 的登录过期处理', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    setUnauthorizedHandler(null)
    fetchMock.mockReset()
    vi.unstubAllGlobals()
  })

  it('普通接口返回 401 时调用处理函数，并仍抛出 ApiError', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: 'Not authenticated' }))

    const error = await api.get('/imports/data?limit=100').catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(401)
    expect((error as ApiError).message).toBe('Not authenticated')
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it.each(['/auth/login', '/auth/me'])('%s 返回 401 时不调用处理函数', async (path) => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: '用户名或密码错误' }))

    await expect(api.post(path, {})).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })

  it('非 401 错误不调用处理函数', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: '服务器错误' }))

    await expect(api.get('/plans')).rejects.toMatchObject({ status: 500, message: '服务器错误' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('setUnauthorizedHandler(null) 注销后不再调用', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    setUnauthorizedHandler(null)
    fetchMock.mockResolvedValue(jsonResponse(401, { detail: 'Not authenticated' }))

    await expect(api.get('/plans')).rejects.toBeInstanceOf(ApiError)
    expect(handler).not.toHaveBeenCalled()
  })
})
