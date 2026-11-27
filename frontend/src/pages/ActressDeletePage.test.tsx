import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { message } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ActressCandidateItem,
  ActressCandidateListResponse,
  ActressDeleteBatchDetail,
  ActressDeleteBatchSummary,
} from '@/api/actresses'
import { ApiError } from '@/api/client'

const listCandidates = vi.fn()
const selectCandidates = vi.fn()
const keepCandidates = vi.fn()
const checkCandidatesRemote = vi.fn()
const listKept = vi.fn()
const removeKept = vi.fn()
const createDeleteBatch = vi.fn()
const listDeleteBatches = vi.fn()
const getDeleteBatch = vi.fn()
const resumeDeleteBatch = vi.fn()

vi.mock('@/api/actresses', () => ({
  listCandidates: (...args: unknown[]) => listCandidates(...args),
  selectCandidates: (...args: unknown[]) => selectCandidates(...args),
  keepCandidates: (...args: unknown[]) => keepCandidates(...args),
  checkCandidatesRemote: (...args: unknown[]) => checkCandidatesRemote(...args),
  listKept: (...args: unknown[]) => listKept(...args),
  removeKept: (...args: unknown[]) => removeKept(...args),
  createDeleteBatch: (...args: unknown[]) => createDeleteBatch(...args),
  listDeleteBatches: (...args: unknown[]) => listDeleteBatches(...args),
  getDeleteBatch: (...args: unknown[]) => getDeleteBatch(...args),
  resumeDeleteBatch: (...args: unknown[]) => resumeDeleteBatch(...args),
}))

const { default: ActressDeletePage } = await import('./ActressDeletePage')

// antd 两个汉字的按钮会在字间插空格，按钮名按「字间可有空白」匹配
function buttonName(label: string) {
  return new RegExp(`^${[...label].join('\\s*')}$`)
}

function confirmText(count: number) {
  return `将删除 ${count} 部片子的 115 原文件和本地 STRM，115 文件进回收站；同名的 nfo、图片、字幕一起清掉。确定？`
}

// 测试数据全部是占位名（甲、乙、丙）和占位番号
function makeCandidate(overrides: Partial<ActressCandidateItem> = {}): ActressCandidateItem {
  return {
    film_dir: '/strm/甲/ABC-001',
    number: 'ABC-001',
    title: '示例标题一',
    selected: true,
    added_by: 'mark',
    added_at: '2026-11-20T10:00:00Z',
    black_names: ['甲'],
    other_actors: [{ name: '乙', status: 'none' }],
    remote_state: 'unchecked',
    remote_note: null,
    ...overrides,
  }
}

function secondCandidate(overrides: Partial<ActressCandidateItem> = {}) {
  return makeCandidate({
    film_dir: '/strm/丙/ABC-002',
    number: 'ABC-002',
    title: '示例标题二',
    black_names: ['丙'],
    other_actors: [],
    remote_state: 'error',
    remote_note: '路径解析失败',
    ...overrides,
  })
}

function makeCandidates(items: ActressCandidateItem[]): ActressCandidateListResponse {
  return { items, total: items.length, selected: items.filter((item) => item.selected).length }
}

function makeSummary(overrides: Partial<ActressDeleteBatchSummary> = {}): ActressDeleteBatchSummary {
  return {
    id: 7,
    job_id: 'job-7',
    status: 'completed',
    created_at: '2026-11-26T10:00:00Z',
    started_at: '2026-11-26T10:00:01Z',
    finished_at: '2026-11-26T10:00:05Z',
    deleted_films: 1,
    failed_films: 0,
    skipped_films: 0,
    jellyfin_refresh: 'done',
    note: null,
    ...overrides,
  }
}

function makeBatchDetail(overrides: Partial<ActressDeleteBatchDetail> = {}): ActressDeleteBatchDetail {
  return {
    ...makeSummary(),
    films: [
      {
        id: 1,
        film_dir: '/strm/甲/ABC-001',
        number: 'ABC-001',
        status: 'deleted',
        reason: null,
        error: null,
        finished_at: '2026-11-26T10:00:04Z',
        files: [
          {
            id: 11,
            group: 'remote_115',
            target: '/115/示例/ABC-001.mp4',
            remote_file_id: 'f-1',
            status: 'deleted',
            error: null,
            executed_at: '2026-11-26T10:00:02Z',
          },
          {
            id: 12,
            group: 'source_strm',
            target: '/porn_tv1/示例/ABC-001.strm',
            remote_file_id: null,
            status: 'deleted',
            error: null,
            executed_at: '2026-11-26T10:00:03Z',
          },
        ],
      },
    ],
    ...overrides,
  }
}

function tabByName(name: string) {
  return screen.getByRole('tab', { name })
}

function confirmButton() {
  return screen.getByRole('button', { name: '确认删除' })
}

// 表格行里的按钮按文字找：在行内用 getByRole 要逐层算样式判断可见性，jsdom 里一次要好几秒
function buttonIn(container: HTMLElement, label: string) {
  return within(container).getByText(buttonName(label)).closest('button') as HTMLButtonElement
}

describe('ActressDeletePage', () => {
  beforeEach(() => {
    listCandidates.mockResolvedValue(makeCandidates([makeCandidate(), secondCandidate()]))
    selectCandidates.mockImplementation(async (dirs: string[]) => ({ count: dirs.length }))
    keepCandidates.mockResolvedValue({ count: 1 })
    checkCandidatesRemote.mockImplementation(async (dirs: string[]) => ({ count: dirs.length }))
    listKept.mockResolvedValue({ items: [] })
    removeKept.mockResolvedValue({ count: 1 })
    listDeleteBatches.mockResolvedValue({ items: [] })
    getDeleteBatch.mockResolvedValue(makeBatchDetail())
    vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.clearAllMocks()
    vi.restoreAllMocks()
  })

  it('只把勾选的片子算进本次删除，不勾选的留在清单', async () => {
    listCandidates.mockResolvedValue(makeCandidates([makeCandidate(), secondCandidate({ selected: false })]))
    createDeleteBatch.mockResolvedValue({ batch_id: 7, job_id: 'job-7' })
    render(<ActressDeletePage />)

    // 打开页面时按服务端保存的勾选状态显示
    expect(await screen.findByText('待删 2 部，本次勾选 1 部')).toBeInTheDocument()
    expect(screen.getByLabelText('勾选 ABC-001')).toBeChecked()
    expect(screen.getByLabelText('勾选 ABC-002')).not.toBeChecked()
    // 行内信息：因为谁、同片演员及状态、115 状态
    const row = screen.getByText('ABC-002').closest('tr') as HTMLElement
    expect(within(row).getByText('丙')).toBeInTheDocument()
    expect(within(row).getByText('有问题：路径解析失败')).toBeInTheDocument()
    expect(screen.getByText('乙（未标）')).toBeInTheDocument()

    // 改勾选：取消 001、勾上 002，每次都同步到服务端
    fireEvent.click(screen.getByLabelText('勾选 ABC-001'))
    await waitFor(() => expect(selectCandidates).toHaveBeenCalledWith(['/strm/甲/ABC-001'], false))
    // 勾选同步在途时勾选框不可点，等它结束
    await waitFor(() => expect(screen.getByLabelText('勾选 ABC-002')).toBeEnabled())
    fireEvent.click(screen.getByLabelText('勾选 ABC-002'))
    await waitFor(() => expect(selectCandidates).toHaveBeenCalledWith(['/strm/丙/ABC-002'], true))
    expect(screen.getByText('待删 2 部，本次勾选 1 部')).toBeInTheDocument()

    await waitFor(() => expect(confirmButton()).toBeEnabled())
    fireEvent.click(confirmButton())
    expect(await screen.findByText(confirmText(1))).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确定删除' }))
    // 只删本次勾选的 002；没勾的 001 不在请求里
    await waitFor(() => expect(createDeleteBatch).toHaveBeenCalledWith(['/strm/丙/ABC-002']))
    expect(createDeleteBatch).toHaveBeenCalledTimes(1)
  })

  it('确认删除前弹确认框，确定后用本次勾选的 film_dirs 调用 createDeleteBatch', async () => {
    createDeleteBatch.mockResolvedValue({ batch_id: 7, job_id: 'job-7' })
    listDeleteBatches.mockResolvedValue({ items: [makeSummary({ id: 7, status: 'completed' })] })
    getDeleteBatch.mockResolvedValue(makeBatchDetail({ id: 7 }))
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 2 部，本次勾选 2 部')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(await screen.findByText(confirmText(2))).toBeInTheDocument()
    // 弹框还没确定，不建批次
    expect(createDeleteBatch).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '确定删除' }))
    await waitFor(() =>
      expect(createDeleteBatch).toHaveBeenCalledWith(['/strm/甲/ABC-001', '/strm/丙/ABC-002']),
    )
    // 成功后切到「历史批次」并打开这个批次
    await waitFor(() => expect(getDeleteBatch).toHaveBeenCalledWith(7))
    expect(tabByName('历史批次')).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('批次 #7')).toBeInTheDocument()
    expect(screen.getByText('/115/示例/ABC-001.mp4')).toBeInTheDocument()
  })

  it('createDeleteBatch 返回 409 时提示清单有变化并重新拉取清单', async () => {
    const detail = '清单有变化，请刷新后再确认（1 部已不在待删清单里）'
    listCandidates
      .mockResolvedValueOnce(makeCandidates([makeCandidate(), secondCandidate()]))
      .mockResolvedValue(makeCandidates([makeCandidate()]))
    createDeleteBatch.mockRejectedValue(new ApiError(409, detail))
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 2 部，本次勾选 2 部')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    fireEvent.click(await screen.findByRole('button', { name: '确定删除' }))
    await waitFor(() => expect(createDeleteBatch).toHaveBeenCalledTimes(1))

    // 显示后端原话，重新拉取清单，留在待删清单页
    await waitFor(() => expect(message.error).toHaveBeenCalledWith(detail))
    await waitFor(() => expect(listCandidates).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('待删 1 部，本次勾选 1 部')).toBeInTheDocument()
    expect(tabByName('待删清单')).toHaveAttribute('aria-selected', 'true')
    expect(getDeleteBatch).not.toHaveBeenCalled()
  })

  it('建删除批次请求在途时勾选和其他按钮不可点', async () => {
    let finishCreate: (value: { batch_id: number; job_id: string }) => void = () => {}
    createDeleteBatch.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishCreate = resolve
        }),
    )
    listDeleteBatches.mockResolvedValue({ items: [makeSummary({ id: 7, status: 'completed' })] })
    getDeleteBatch.mockResolvedValue(makeBatchDetail({ id: 7 }))
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 2 部，本次勾选 2 部')).toBeInTheDocument()

    fireEvent.click(confirmButton())
    fireEvent.click(await screen.findByRole('button', { name: '确定删除' }))
    await waitFor(() => expect(createDeleteBatch).toHaveBeenCalledTimes(1))
    // 请求在途：勾选改不了，否则服务端勾选和本次删除的片子会对不上
    expect(screen.getByLabelText('勾选 ABC-001')).toBeDisabled()
    expect(screen.getByRole('button', { name: '检查 115' })).toBeDisabled()
    expect(screen.getByText(buttonName('全不选')).closest('button')).toBeDisabled()

    await act(async () => {
      finishCreate({ batch_id: 7, job_id: 'job-7' })
    })
    await waitFor(() => expect(getDeleteBatch).toHaveBeenCalledWith(7))
  })

  it('勾选同步请求在途时确认删除等按钮不可点', async () => {
    let finishSelect: (value: { count: number }) => void = () => {}
    selectCandidates.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishSelect = resolve
        }),
    )
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 2 部，本次勾选 2 部')).toBeInTheDocument()
    expect(confirmButton()).toBeEnabled()

    fireEvent.click(screen.getByLabelText('勾选 ABC-001'))
    await waitFor(() => expect(selectCandidates).toHaveBeenCalledTimes(1))
    expect(confirmButton()).toBeDisabled()
    expect(screen.getByLabelText('勾选 ABC-002')).toBeDisabled()
    expect(screen.getByRole('button', { name: '检查 115' })).toBeDisabled()
    expect(screen.getByText(buttonName('全选')).closest('button')).toBeDisabled()
    expect(screen.getByText(buttonName('全不选')).closest('button')).toBeDisabled()

    await act(async () => {
      finishSelect({ count: 1 })
    })
    await waitFor(() => expect(confirmButton()).toBeEnabled())
    expect(screen.getByText('待删 2 部，本次勾选 1 部')).toBeInTheDocument()
  })

  it('清单重拉期间确认删除不可点，重拉回来的旧数据不会把取消的勾选带进删除请求', async () => {
    let finishReload: (value: ActressCandidateListResponse) => void = () => {}
    listCandidates
      .mockResolvedValueOnce(makeCandidates([makeCandidate(), secondCandidate()]))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finishReload = resolve
          }),
      )
    createDeleteBatch.mockResolvedValue({ batch_id: 7, job_id: 'job-7' })
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 2 部，本次勾选 2 部')).toBeInTheDocument()

    // 检查 115 结束后静默重拉清单；重拉挂起
    fireEvent.click(screen.getByRole('button', { name: '检查 115' }))
    await waitFor(() => expect(listCandidates).toHaveBeenCalledTimes(2))
    expect(confirmButton()).toBeDisabled()
    expect(screen.getByLabelText('勾选 ABC-001')).toBeDisabled()
    // 重拉期间点勾选框不起作用，不会出现「页面已取消、重拉又勾回」
    fireEvent.click(screen.getByLabelText('勾选 ABC-001'))
    expect(selectCandidates).not.toHaveBeenCalled()

    // 重拉返回旧数据（两部都勾着）
    await act(async () => {
      finishReload(makeCandidates([makeCandidate(), secondCandidate()]))
    })
    await waitFor(() => expect(screen.getByLabelText('勾选 ABC-001')).toBeEnabled())
    expect(screen.getByLabelText('勾选 ABC-001')).toBeChecked()

    // 重拉结束后再取消 001，确认时请求里没有它
    fireEvent.click(screen.getByLabelText('勾选 ABC-001'))
    await waitFor(() => expect(selectCandidates).toHaveBeenCalledWith(['/strm/甲/ABC-001'], false))
    await waitFor(() => expect(confirmButton()).toBeEnabled())
    fireEvent.click(confirmButton())
    expect(await screen.findByText(confirmText(1))).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确定删除' }))
    await waitFor(() => expect(createDeleteBatch).toHaveBeenCalledWith(['/strm/丙/ABC-002']))
  })

  it('确认框打开后清单有变化时不发送旧快照', async () => {
    listCandidates
      .mockResolvedValueOnce(makeCandidates([makeCandidate(), secondCandidate()]))
      .mockResolvedValue(makeCandidates([makeCandidate(), secondCandidate({ selected: false })]))
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 2 部，本次勾选 2 部')).toBeInTheDocument()

    fireEvent.click(confirmButton())
    expect(await screen.findByText(confirmText(2))).toBeInTheDocument()
    // 确认框打开期间不能再点「确认删除」叠出第二个框
    expect(confirmButton()).toBeDisabled()

    // 框打开期间清单被重拉，勾选变成 1 部
    fireEvent.click(screen.getByText(buttonName('刷新')).closest('button') as HTMLButtonElement)
    expect(await screen.findByText('待删 2 部，本次勾选 1 部')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '确定删除' }))
    await waitFor(() => expect(message.warning).toHaveBeenCalledWith('清单有变化，请重新确认'))
    expect(createDeleteBatch).not.toHaveBeenCalled()
    await waitFor(() => expect(confirmButton()).toBeEnabled())
  })

  it('点保留后调用 keepCandidates 并从列表移除', async () => {
    render(<ActressDeletePage />)
    const row = (await screen.findByText('ABC-001')).closest('tr') as HTMLElement
    fireEvent.click(buttonIn(row, '保留'))

    await waitFor(() => expect(keepCandidates).toHaveBeenCalledWith(['/strm/甲/ABC-001']))
    await waitFor(() => expect(screen.queryByText('ABC-001')).not.toBeInTheDocument())
    expect(screen.getByText('ABC-002')).toBeInTheDocument()
    expect(screen.getByText('待删 1 部，本次勾选 1 部')).toBeInTheDocument()
  })

  it('检查 115 对勾选的片子按每批最多 50 部分批调用', async () => {
    const items = Array.from({ length: 120 }, (_, index) => {
      const number = `ABC-${String(index + 1).padStart(3, '0')}`
      return makeCandidate({ film_dir: `/strm/甲/${number}`, number })
    })
    // 第 120 部不勾，不参与检查
    items[119] = { ...items[119], selected: false }
    listCandidates.mockResolvedValue(makeCandidates(items))
    render(<ActressDeletePage />)
    expect(await screen.findByText('待删 120 部，本次勾选 119 部')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '检查 115' }))
    await waitFor(() => expect(checkCandidatesRemote).toHaveBeenCalledTimes(3))
    const sizes = checkCandidatesRemote.mock.calls.map((call) => (call[0] as string[]).length)
    expect(sizes).toEqual([50, 50, 19])
    expect(checkCandidatesRemote.mock.calls.flatMap((call) => call[0] as string[])).not.toContain('/strm/甲/ABC-120')
    // 检查完重新拉取清单，显示 115 状态
    await waitFor(() => expect(listCandidates).toHaveBeenCalledTimes(2))
  })

  it('批次运行中轮询，完成后停止', async () => {
    // 只假造轮询用的 setTimeout；动画帧、Date 等保持真实，避免拖慢 antd 组件
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    // 等异步请求和渲染落定
    const flush = async () => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0)
      })
    }
    listDeleteBatches.mockResolvedValue({ items: [makeSummary({ id: 3, status: 'running', finished_at: null })] })
    getDeleteBatch
      .mockResolvedValueOnce(makeBatchDetail({ id: 3, status: 'running', finished_at: null }))
      .mockResolvedValueOnce(makeBatchDetail({ id: 3, status: 'running', finished_at: null }))
      .mockResolvedValue(makeBatchDetail({ id: 3, status: 'completed' }))
    render(<ActressDeletePage />)
    await flush()

    fireEvent.click(tabByName('历史批次'))
    await flush()
    const row = screen.getByText('#3').closest('tr') as HTMLElement
    fireEvent.click(buttonIn(row, '查看'))
    await flush()
    expect(getDeleteBatch).toHaveBeenCalledTimes(1)
    expect(getDeleteBatch).toHaveBeenCalledWith(3)
    expect(screen.getByText('执行中，每 3 秒自动刷新…')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(getDeleteBatch).toHaveBeenCalledTimes(2)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(getDeleteBatch).toHaveBeenCalledTimes(3)
    expect(screen.queryByText('执行中，每 3 秒自动刷新…')).not.toBeInTheDocument()

    // 已完成：不再请求
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(getDeleteBatch).toHaveBeenCalledTimes(3)
  })

  it('失败批次显示重试按钮', async () => {
    listDeleteBatches.mockResolvedValue({
      items: [
        makeSummary({ id: 6, status: 'interrupted', note: '删除中断：示例' }),
        makeSummary({ id: 5, status: 'completed' }),
        makeSummary({ id: 4, status: 'failed', failed_films: 1, finished_at: '2026-11-25T10:00:05Z' }),
      ],
    })
    resumeDeleteBatch.mockResolvedValue({ batch_id: 4, job_id: 'job-9' })
    // 续跑完成后完成时间更新，轮询停止
    getDeleteBatch.mockResolvedValue(makeBatchDetail({ id: 4, status: 'completed', finished_at: '2026-11-26T11:00:00Z' }))
    render(<ActressDeletePage />)
    await screen.findByText('待删 2 部，本次勾选 2 部')
    fireEvent.click(tabByName('历史批次'))

    const failedRow = (await screen.findByText('#4')).closest('tr') as HTMLElement
    const interruptedRow = screen.getByText('#6').closest('tr') as HTMLElement
    const completedRow = screen.getByText('#5').closest('tr') as HTMLElement
    expect(buttonIn(interruptedRow, '重试失败的')).toBeInTheDocument()
    expect(within(completedRow).queryByText('重试失败的')).not.toBeInTheDocument()

    fireEvent.click(buttonIn(failedRow, '重试失败的'))
    await waitFor(() => expect(resumeDeleteBatch).toHaveBeenCalledWith(4))
    // 重试后打开这个批次看进度
    await waitFor(() => expect(getDeleteBatch).toHaveBeenCalledWith(4))
    expect(await screen.findByText('批次 #4')).toBeInTheDocument()
  })

  it('保留名单里撤销保留后调用 removeKept 并移出名单', async () => {
    listKept.mockResolvedValue({
      items: [{ film_dir: '/strm/甲/ABC-003', number: 'ABC-003', created_at: '2026-11-24T10:00:00Z' }],
    })
    render(<ActressDeletePage />)
    await screen.findByText('待删 2 部，本次勾选 2 部')
    fireEvent.click(tabByName('保留名单'))

    const row = (await screen.findByText('ABC-003')).closest('tr') as HTMLElement
    fireEvent.click(buttonIn(row, '撤销保留'))
    await waitFor(() => expect(removeKept).toHaveBeenCalledWith(['/strm/甲/ABC-003']))
    await waitFor(() => expect(screen.queryByText('ABC-003')).not.toBeInTheDocument())
  })
})
