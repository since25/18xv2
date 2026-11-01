import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useUndoableIgnore } from './useUndoableIgnore'

describe('useUndoableIgnore', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('commits once after the five second delay', async () => {
    const commit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useUndoableIgnore({ commit }))

    act(() => result.current.schedule([{ packageId: 1, title: 'A' }]))
    await act(async () => {
      vi.advanceTimersByTime(4999)
      await Promise.resolve()
    })
    expect(commit).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(1)
      await Promise.resolve()
    })
    expect(commit).toHaveBeenCalledWith([1])
  })

  it('cancels a scheduled commit when undo is called', async () => {
    const commit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useUndoableIgnore({ commit }))
    act(() => result.current.schedule([{ packageId: 1, title: 'A' }]))
    act(() => result.current.undo())
    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
    })
    expect(commit).not.toHaveBeenCalled()
  })

  it('commits the previous batch before starting a new timer', async () => {
    const commit = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useUndoableIgnore({ commit }))
    act(() => result.current.schedule([{ packageId: 1, title: 'A' }]))
    act(() => result.current.schedule([{ packageId: 2, title: 'B' }]))
    expect(commit).toHaveBeenCalledWith([1])
    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
    })
    expect(commit).toHaveBeenCalledWith([2])
  })

  it('flushes pending work when the hook unmounts', async () => {
    const commit = vi.fn().mockResolvedValue(undefined)
    const { result, unmount } = renderHook(() => useUndoableIgnore({ commit }))
    act(() => result.current.schedule([{ packageId: 1, title: 'A' }]))
    unmount()
    await act(async () => {
      await Promise.resolve()
    })
    expect(commit).toHaveBeenCalledWith([1])
  })

  it('clears pending ids when commit fails', async () => {
    const commit = vi.fn().mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useUndoableIgnore({ commit }))
    act(() => result.current.schedule([{ packageId: 1, title: 'A' }]))
    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(result.current.pendingIds).toEqual(new Set())
  })
})
