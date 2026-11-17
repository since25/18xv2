import { act, renderHook } from '@testing-library/react'
import { message } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useApiAction } from './useApiAction'

function apiError(status: number, text: string) {
  return Object.assign(new Error(text), { status })
}

describe('useApiAction', () => {

  beforeEach(() => {
    vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('成功时返回 { ok: true, data }，按字符串提示并调用 onSuccess', async () => {
    const onSuccess = vi.fn()
    const fn = vi.fn((id: number) => Promise.resolve({ id }))
    const { result } = renderHook(() => useApiAction(fn, { successMessage: '已保存', onSuccess }))
    let outcome: Awaited<ReturnType<typeof result.current.run>> | undefined
    await act(async () => {
      outcome = await result.current.run(7)
    })
    expect(outcome).toEqual({ ok: true, data: { id: 7 } })
    expect(fn).toHaveBeenCalledWith(7)
    expect(message.success).toHaveBeenCalledWith('已保存')
    expect(onSuccess).toHaveBeenCalledWith({ id: 7 }, 7)
    expect(message.error).not.toHaveBeenCalled()
  })

  it('successMessage 为函数时用返回数据和参数生成提示', async () => {
    const { result } = renderHook(() =>
      useApiAction((id: number) => Promise.resolve({ count: id - 2 }), {
        successMessage: (data, id) => `批次 #${id} 删除 ${data.count} 条`,
      }))
    await act(async () => {
      await result.current.run(5)
    })
    expect(message.success).toHaveBeenCalledWith('批次 #5 删除 3 条')
  })

  it('未设置 successMessage 时不弹成功提示', async () => {
    const { result } = renderHook(() => useApiAction(() => Promise.resolve(1)))
    await act(async () => {
      await result.current.run()
    })
    expect(message.success).not.toHaveBeenCalled()
  })

  it('失败时返回 { ok: false, error } 并提示错误，不调用 onSuccess、不抛异常', async () => {
    const onSuccess = vi.fn()
    const { result } = renderHook(() =>
      useApiAction(() => Promise.reject(new Error('操作失败')), { successMessage: '成功', onSuccess }))
    let outcome: Awaited<ReturnType<typeof result.current.run>> | undefined
    await act(async () => {
      outcome = await result.current.run()
    })
    expect(outcome?.ok).toBe(false)
    expect(outcome && !outcome.ok ? outcome.error.message : '').toBe('操作失败')
    expect(message.error).toHaveBeenCalledWith('操作失败')
    expect(message.success).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('silent 时失败不提示', async () => {
    const { result } = renderHook(() =>
      useApiAction(() => Promise.reject(new Error('静默失败')), { silent: true }))
    let outcome: Awaited<ReturnType<typeof result.current.run>> | undefined
    await act(async () => {
      outcome = await result.current.run()
    })
    expect(outcome?.ok).toBe(false)
    expect(message.error).not.toHaveBeenCalled()
  })

  it('401 时不提示', async () => {
    const { result } = renderHook(() => useApiAction(() => Promise.reject(apiError(401, 'Unauthorized'))))
    let outcome: Awaited<ReturnType<typeof result.current.run>> | undefined
    await act(async () => {
      outcome = await result.current.run()
    })
    expect(outcome?.ok).toBe(false)
    expect(message.error).not.toHaveBeenCalled()
  })

  it('执行期间 loading 为真，结束后为假', async () => {
    let resolve!: (value: string) => void
    const { result } = renderHook(() =>
      useApiAction(() => new Promise<string>((res) => {
        resolve = res
      })))
    expect(result.current.loading).toBe(false)
    let runPromise!: Promise<unknown>
    act(() => {
      runPromise = result.current.run()
    })
    expect(result.current.loading).toBe(true)
    await act(async () => {
      resolve('done')
      await runPromise
    })
    expect(result.current.loading).toBe(false)
  })

  it('执行函数同步抛错时 run 也不抛异常', async () => {
    const { result } = renderHook(() =>
      useApiAction((): Promise<void> => {
        throw new Error('同步错误')
      }))
    let outcome: Awaited<ReturnType<typeof result.current.run>> | undefined
    await act(async () => {
      outcome = await result.current.run()
    })
    expect(outcome?.ok).toBe(false)
    expect(message.error).toHaveBeenCalledWith('同步错误')
    expect(result.current.loading).toBe(false)
  })
})
