import { act, renderHook, waitFor } from '@testing-library/react'
import { message } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useApiQuery } from './useApiQuery'

// 手动控制何时返回的 Promise
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function apiError(status: number, text: string) {
  return Object.assign(new Error(text), { status })
}

describe('useApiQuery', () => {

  beforeEach(() => {
    vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('挂载时自动执行并返回数据，loading 先真后假', async () => {
    const d = deferred<string>()
    const fetcher = vi.fn(() => d.promise)
    const { result } = renderHook(() => useApiQuery(fetcher, []))
    expect(result.current.loading).toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(1)
    await act(async () => {
      d.resolve('ok')
    })
    expect(result.current.data).toBe('ok')
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('依赖变化时重新执行', async () => {
    const fetcher = vi.fn((id: number) => Promise.resolve(`item-${id}`))
    const { result, rerender } = renderHook(({ id }) => useApiQuery(() => fetcher(id), [id]), {
      initialProps: { id: 1 },
    })
    await waitFor(() => expect(result.current.data).toBe('item-1'))
    rerender({ id: 2 })
    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.data).toBe('item-2'))
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(result.current.loading).toBe(false)
  })

  it('依赖不变时重新渲染不会重复请求', async () => {
    const fetcher = vi.fn(() => Promise.resolve(1))
    const { result, rerender } = renderHook(() => useApiQuery(fetcher, ['same']))
    await waitFor(() => expect(result.current.loading).toBe(false))
    rerender()
    rerender()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('enabled 为 false 时不执行，变为 true 后执行', async () => {
    const fetcher = vi.fn(() => Promise.resolve('x'))
    const { result, rerender } = renderHook(({ enabled }) => useApiQuery(fetcher, [], { enabled }), {
      initialProps: { enabled: false },
    })
    expect(result.current.loading).toBe(false)
    await act(async () => {})
    expect(fetcher).not.toHaveBeenCalled()
    rerender({ enabled: true })
    await waitFor(() => expect(result.current.data).toBe('x'))
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('先发后到的旧结果被丢弃，显示后一次的结果', async () => {
    const first = deferred<string>()
    const second = deferred<string>()
    const fetchers: Record<number, () => Promise<string>> = { 1: () => first.promise, 2: () => second.promise }
    const { result, rerender } = renderHook(({ id }) => useApiQuery(fetchers[id], [id]), {
      initialProps: { id: 1 },
    })
    rerender({ id: 2 })
    await act(async () => {
      second.resolve('second')
    })
    expect(result.current.data).toBe('second')
    expect(result.current.loading).toBe(false)
    await act(async () => {
      first.resolve('first')
    })
    expect(result.current.data).toBe('second')
  })

  it('旧请求后返回的错误也被丢弃，不弹提示', async () => {
    const first = deferred<string>()
    const fetchers: Record<number, () => Promise<string>> = {
      1: () => first.promise,
      2: () => Promise.resolve('second'),
    }
    const { result, rerender } = renderHook(({ id }) => useApiQuery(fetchers[id], [id]), {
      initialProps: { id: 1 },
    })
    rerender({ id: 2 })
    await waitFor(() => expect(result.current.data).toBe('second'))
    await act(async () => {
      first.reject(new Error('旧请求失败'))
    })
    expect(result.current.error).toBeNull()
    expect(message.error).not.toHaveBeenCalled()
  })

  it('卸载后返回不更新状态、不报 React 警告、不弹提示', async () => {
    const consoleSpy = vi.spyOn(console, 'error')
    const d = deferred<string>()
    const { result, unmount } = renderHook(() => useApiQuery(() => d.promise, []))
    unmount()
    await act(async () => {
      d.reject(new Error('卸载后失败'))
    })
    expect(result.current.data).toBeUndefined()
    expect(result.current.loading).toBe(true)
    expect(message.error).not.toHaveBeenCalled()
    expect(consoleSpy).not.toHaveBeenCalled()
  })

  it('出错时 error 有值并调用 message.error', async () => {
    const { result } = renderHook(() => useApiQuery(() => Promise.reject(new Error('加载失败')), []))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error?.message).toBe('加载失败')
    expect(message.error).toHaveBeenCalledWith('加载失败')
  })

  it('silent 时出错不弹提示', async () => {
    const { result } = renderHook(() =>
      useApiQuery(() => Promise.reject(new Error('静默失败')), [], { silent: true }))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error?.message).toBe('静默失败')
    expect(message.error).not.toHaveBeenCalled()
  })

  it('401 时不弹提示', async () => {
    const { result } = renderHook(() => useApiQuery(() => Promise.reject(apiError(401, 'Unauthorized')), []))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error?.message).toBe('Unauthorized')
    expect(message.error).not.toHaveBeenCalled()
  })

  it('reload() 重新取数，期间 loading 为真且保留旧数据', async () => {
    let count = 0
    const pending: Array<ReturnType<typeof deferred<number>>> = []
    const fetcher = vi.fn(() => {
      count += 1
      if (count === 1) return Promise.resolve(1)
      const next = deferred<number>()
      pending.push(next)
      return next.promise
    })
    const { result } = renderHook(() => useApiQuery(fetcher, []))
    await waitFor(() => expect(result.current.data).toBe(1))
    let reloadPromise!: Promise<void>
    act(() => {
      reloadPromise = result.current.reload()
    })
    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBe(1)
    await act(async () => {
      pending[0].resolve(2)
      await reloadPromise
    })
    expect(result.current.data).toBe(2)
    expect(result.current.loading).toBe(false)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('reload({ silent: true }) 期间 loading 保持假', async () => {
    let count = 0
    const pending: Array<ReturnType<typeof deferred<number>>> = []
    const fetcher = vi.fn(() => {
      count += 1
      if (count === 1) return Promise.resolve(1)
      const next = deferred<number>()
      pending.push(next)
      return next.promise
    })
    const { result } = renderHook(() => useApiQuery(fetcher, []))
    await waitFor(() => expect(result.current.data).toBe(1))
    let reloadPromise!: Promise<void>
    act(() => {
      reloadPromise = result.current.reload({ silent: true })
    })
    expect(result.current.loading).toBe(false)
    await act(async () => {
      pending[0].resolve(2)
      await reloadPromise
    })
    expect(result.current.data).toBe(2)
    expect(result.current.loading).toBe(false)
  })

  it('依赖变化重新加载期间保留旧数据', async () => {
    const second = deferred<string>()
    const fetchers: Record<number, () => Promise<string>> = {
      1: () => Promise.resolve('first'),
      2: () => second.promise,
    }
    const { result, rerender } = renderHook(({ id }) => useApiQuery(fetchers[id], [id]), {
      initialProps: { id: 1 },
    })
    await waitFor(() => expect(result.current.data).toBe('first'))
    rerender({ id: 2 })
    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBe('first')
    await act(async () => {
      second.resolve('second')
    })
    expect(result.current.data).toBe('second')
  })

  it('initialData 生效', () => {
    const d = deferred<string[]>()
    const { result } = renderHook(() => useApiQuery(() => d.promise, [], { initialData: ['init'] }))
    expect(result.current.data).toEqual(['init'])
  })

  it('setData 可直接改数据（值与函数两种）', async () => {
    const { result } = renderHook(() => useApiQuery(() => Promise.resolve([1]), [], { initialData: [] as number[] }))
    await waitFor(() => expect(result.current.data).toEqual([1]))
    act(() => {
      result.current.setData([5])
    })
    expect(result.current.data).toEqual([5])
    act(() => {
      result.current.setData((prev) => [...(prev ?? []), 6])
    })
    expect(result.current.data).toEqual([5, 6])
  })
})
