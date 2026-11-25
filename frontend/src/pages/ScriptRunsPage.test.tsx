import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ScriptRunSummary } from '@/api/scriptRuns'
import { ZERO, buttonName, makeJob, makeRun } from './scriptCenter/testData'

const getScriptRunSummary = vi.fn()
const listScriptRuns = vi.fn()
const listScriptRunItems = vi.fn()
const stopScriptRun = vi.fn()
const getScriptRunLog = vi.fn()
const listScriptJobs = vi.fn()
const startScriptJobRun = vi.fn()

vi.mock('@/api/scriptRuns', () => ({
  getScriptRunSummary: (...args: unknown[]) => getScriptRunSummary(...args),
  listScriptRuns: (...args: unknown[]) => listScriptRuns(...args),
  listScriptRunItems: (...args: unknown[]) => listScriptRunItems(...args),
  stopScriptRun: (...args: unknown[]) => stopScriptRun(...args),
  getScriptRunLog: (...args: unknown[]) => getScriptRunLog(...args),
}))

vi.mock('@/api/scriptJobs', () => ({
  listScriptJobs: (...args: unknown[]) => listScriptJobs(...args),
  startScriptJobRun: (...args: unknown[]) => startScriptJobRun(...args),
  updateScriptJob: vi.fn(),
  updateSiteSession: vi.fn(),
}))

const { default: ScriptRunsPage } = await import('./ScriptRunsPage')

function makeSummary(overrides: Partial<ScriptRunSummary> = {}): ScriptRunSummary {
  return {
    timezone: 'Asia/Shanghai',
    days: [
      { date: '2026-10-31', has_run: false, cleaned: 0, moved_new: 0 },
      { date: '2026-11-01', has_run: true, cleaned: 50, moved_new: 12 },
    ],
    scripts: [
      { script_name: 'DEL_SOMETHING', expected_time: '12:09', executor: 'unraid', enabled: false, latest_run: null, today_status: 'success' },
      { script_name: 'MOVE_SSD_CACHE_TO_DISK2', expected_time: '01:01', executor: 'unraid', enabled: false, latest_run: null, today_status: 'missing' },
    ],
    ...overrides,
  }
}

describe('ScriptRunsPage', () => {
  beforeEach(() => {
    listScriptJobs.mockResolvedValue({ items: [makeJob({ executor: 'unraid', enabled: false })] })
    startScriptJobRun.mockResolvedValue({ run_id: 50, status: 'running' })
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

  it('页面名称改为脚本中心，sehuatang 有告警时显示红条', async () => {
    listScriptJobs.mockResolvedValue({
      items: [makeJob({ alert: '站点 cookie 可能失效：列表页全部失败' })],
    })
    render(<ScriptRunsPage />)
    expect(await screen.findByText(/站点 cookie 可能失效：列表页全部失败/)).toBeTruthy()
    expect(screen.getByText(/到设置里更换站点 cookie/)).toBeTruthy()
    expect(screen.getAllByText('脚本中心').length).toBeGreaterThan(0)
  })

  it('运行中的记录 finished_at 为空时不报错，并标出演练和手动', async () => {
    listScriptRuns.mockResolvedValue({
      total: 1,
      items: [
        makeRun({
          id: 7,
          script_name: 'sehuatang',
          status: 'running',
          finished_at: null,
          exit_code: null,
          trigger: 'manual',
          dry_run: true,
          counts: { ...ZERO },
        }),
      ],
    })
    render(<ScriptRunsPage />)
    expect(await screen.findByText('运行中')).toBeTruthy()
    expect(screen.getByText('演练')).toBeTruthy()
    expect(screen.getByText('手动')).toBeTruthy()
    expect(screen.queryByText(/退出码/)).toBeNull()
  })

  it('演练确认后调用接口并刷新任务', async () => {
    render(<ScriptRunsPage />)
    const box = await screen.findByTestId('job-card-sehuatang')
    fireEvent.click(within(box).getByRole('button', { name: buttonName('演练') }))
    fireEvent.click(screen.getByRole('button', { name: buttonName('确定') }))
    await waitFor(() => expect(startScriptJobRun).toHaveBeenCalledWith('sehuatang', true))
    await waitFor(() => expect(listScriptJobs.mock.calls.length).toBeGreaterThan(1))
  })
})
