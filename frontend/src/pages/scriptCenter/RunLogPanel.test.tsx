import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getScriptRunLog = vi.fn()

vi.mock('@/api/scriptRuns', () => ({
  getScriptRunLog: (...args: unknown[]) => getScriptRunLog(...args),
}))

const { default: RunLogPanel } = await import('./RunLogPanel')

describe('RunLogPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('日志面板按 offset 追加，finished 后停止轮询', async () => {
    getScriptRunLog
      .mockResolvedValueOnce({ text: '第一行\n', next_offset: 10, finished: false })
      .mockResolvedValueOnce({ text: '第二行\n', next_offset: 20, finished: true })

    render(<RunLogPanel runId={5} />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(getScriptRunLog).toHaveBeenNthCalledWith(1, 5, 0)
    expect(screen.getByTestId('run-log').textContent).toBe('第一行\n')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(getScriptRunLog).toHaveBeenNthCalledWith(2, 5, 10)
    expect(screen.getByTestId('run-log').textContent).toBe('第一行\n第二行\n')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000)
    })
    expect(getScriptRunLog).toHaveBeenCalledTimes(2)
  })

  it('读取失败时显示错误', async () => {
    getScriptRunLog.mockRejectedValueOnce(new Error('这次运行没有日志'))
    render(<RunLogPanel runId={6} />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByText(/日志加载失败：这次运行没有日志/)).toBeTruthy()
  })
})
