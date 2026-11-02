import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ScriptRun, ScriptRunCounts, ScriptRunSummary } from '@/api/scriptRuns'

const getScriptRunSummary = vi.fn()
const listScriptRuns = vi.fn()
const listScriptRunItems = vi.fn()

vi.mock('@/api/scriptRuns', () => ({
  getScriptRunSummary: (...args: unknown[]) => getScriptRunSummary(...args),
  listScriptRuns: (...args: unknown[]) => listScriptRuns(...args),
  listScriptRunItems: (...args: unknown[]) => listScriptRunItems(...args),
}))

const { default: ScriptRunsPage } = await import('./ScriptRunsPage')

const ZERO: ScriptRunCounts = {
  deleted_dirs: 0, deleted_files: 0, empty_dirs: 0, moved_new: 0, moved_rescan: 0, ambiguous: 0,
  skipped: 0, errors: 0, warnings: 0, unparsed_lines: 0, moved: 0, duplicates_removed: 0, failed: 0,
}

function makeRun(overrides: Partial<ScriptRun> = {}): ScriptRun {
  return {
    id: 1,
    run_key: 'DEL_SOMETHING:1',
    script_name: 'DEL_SOMETHING',
    started_at: '2026-11-01T04:09:00Z',
    finished_at: '2026-11-01T04:10:00Z',
    exit_code: 0,
    status: 'success',
    counts: { ...ZERO, deleted_dirs: 6, deleted_files: 44, moved_new: 12, moved_rescan: 2 },
    items_truncated: false,
    received_at: '2026-11-01T04:10:01Z',
    ...overrides,
  }
}

function makeSummary(overrides: Partial<ScriptRunSummary> = {}): ScriptRunSummary {
  return {
    timezone: 'Asia/Shanghai',
    days: [
      { date: '2026-10-31', has_run: false, cleaned: 0, moved_new: 0 },
      { date: '2026-11-01', has_run: true, cleaned: 50, moved_new: 12 },
    ],
    scripts: [
      { script_name: 'DEL_SOMETHING', expected_time: '12:09', latest_run: null, today_status: 'success' },
      { script_name: 'MOVE_SSD_CACHE_TO_DISK2', expected_time: '01:01', latest_run: null, today_status: 'missing' },
    ],
    ...overrides,
  }
}

describe('ScriptRunsPage', () => {
  beforeEach(() => {
    getScriptRunSummary.mockResolvedValue(makeSummary())
    listScriptRuns.mockResolvedValue({ total: 1, items: [makeRun()] })
    listScriptRunItems.mockImplementation((_id: number, params: { kind?: string }) =>
      Promise.resolve({
        total: 1,
        kind_counts: { deleted_file: 44, moved_new: 12 },
        items:
          params.kind === 'moved_new'
            ? [{ id: 2, kind: 'moved_new', path: '/data/finish/示例资源B', target_path: '/data/已整理/示例词/示例资源B', keyword: '示例词', message: null }]
            : [{ id: 1, kind: 'deleted_file', path: '/data/finish/示例文件A.txt', target_path: null, keyword: null, message: null }],
      }),
    )
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('趋势图区分没有运行和数量为 0，并显示今日缺失状态', async () => {
    render(<ScriptRunsPage />)
    const bar = await screen.findByTestId('bar-清理数量-2026-10-31')
    expect(within(bar).getByText('无记录')).toBeTruthy()
    expect(within(screen.getByTestId('bar-清理数量-2026-11-01')).getByText('50')).toBeTruthy()
    expect(screen.getByText('今天没有运行记录')).toBeTruthy()
  })

  it('运行记录用一句话显示结果，失败时写明退出码和未识别行', async () => {
    listScriptRuns.mockResolvedValue({
      total: 2,
      items: [
        makeRun(),
        makeRun({
          id: 2,
          script_name: 'MOVE_SSD_CACHE_TO_DISK2',
          status: 'failed',
          exit_code: 1,
          counts: { ...ZERO, moved: 12, failed: 1, unparsed_lines: 3 },
        }),
      ],
    })
    render(<ScriptRunsPage />)
    expect(await screen.findByText(/清理 50（目录 6，文件 44），新命中 12，重新归位 2/)).toBeTruthy()
    expect(screen.getByText('移动 12，删除重复 0，跳过 0，失败 1')).toBeTruthy()
    expect(screen.getByText(/退出码 1/)).toBeTruthy()
    expect(screen.getByText(/有 3 行输出没能识别/)).toBeTruthy()
  })

  it('点开一次运行能看到名单，并能切换类别', async () => {
    render(<ScriptRunsPage />)
    fireEvent.click(await screen.findByText(/清理 50/))
    expect(await screen.findByText('/data/finish/示例文件A.txt')).toBeTruthy()
    await waitFor(() => expect(listScriptRunItems).toHaveBeenCalledWith(1, expect.objectContaining({ kind: 'deleted_file' })))

    fireEvent.click(screen.getByText('新命中 12'))
    expect(await screen.findByText('/data/finish/示例资源B')).toBeTruthy()
    expect(screen.getByText('示例词')).toBeTruthy()
  })

  it('没有回报时显示空状态，接口失败时显示错误', async () => {
    listScriptRuns.mockResolvedValue({ total: 0, items: [] })
    getScriptRunSummary.mockRejectedValue(new Error('网络错误'))
    render(<ScriptRunsPage />)
    expect(await screen.findByText('还没有收到脚本回报')).toBeTruthy()
    expect(await screen.findByText(/统计加载失败：网络错误/)).toBeTruthy()
  })
})
