import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import JobCards from './JobCards'
import { DEL_JOB, buttonName, makeJob, makeRun } from './testData'

function renderCards(jobs = [makeJob()]) {
  const onRun = vi.fn()
  const onStop = vi.fn()
  const onSettings = vi.fn()
  const onShowLog = vi.fn()
  render(<JobCards jobs={jobs} onRun={onRun} onStop={onStop} onSettings={onSettings} onShowLog={onShowLog} />)
  return { onRun, onStop, onSettings, onShowLog }
}

function card(label: string) {
  return screen.getByTestId(`job-card-${label}`)
}

describe('JobCards', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('由 Unraid 运行时只显示演练不显示立即运行', () => {
    renderCards([makeJob({ executor: 'unraid', enabled: false })])
    const box = card('sehuatang')
    expect(within(box).getByText('由 Unraid 运行')).toBeTruthy()
    expect(within(box).queryByRole('button', { name: buttonName('立即运行') })).toBeNull()
    expect(within(box).getByRole('button', { name: buttonName('演练') })).toBeTruthy()
  })

  it('18x 停用时显示已停用，启用时显示每天运行时间', () => {
    renderCards([makeJob({ enabled: false }), { ...DEL_JOB, enabled: true }])
    expect(within(card('sehuatang')).getByText('已停用')).toBeTruthy()
    expect(within(card('DEL_SOMETHING')).getByText('每天 12:09')).toBeTruthy()
  })

  it('有运行中任务时显示停止和看日志', () => {
    const active = makeRun({ id: 9, script_name: 'sehuatang', status: 'running', finished_at: null, exit_code: null })
    const { onStop, onShowLog } = renderCards([makeJob({ active_run: active })])
    const box = card('sehuatang')
    expect(within(box).queryByRole('button', { name: buttonName('立即运行') })).toBeNull()
    expect(within(box).getByText(/运行中/)).toBeTruthy()
    fireEvent.click(within(box).getByRole('button', { name: buttonName('看日志') }))
    expect(onShowLog).toHaveBeenCalledWith(active)
    fireEvent.click(within(box).getByRole('button', { name: buttonName('停止') }))
    expect(screen.getByText('停止这次运行？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: buttonName('确定') }))
    expect(onStop).toHaveBeenCalledWith(9)
  })

  it('排队中的任务显示排队中', () => {
    const queued = makeRun({ id: 3, status: 'queued', finished_at: null, exit_code: null })
    renderCards([{ ...DEL_JOB, active_run: queued }])
    expect(within(card('DEL_SOMETHING')).getByText('排队中')).toBeTruthy()
  })

  it('DEL 立即运行确认框包含“会真实删除文件”', () => {
    const { onRun } = renderCards([DEL_JOB])
    fireEvent.click(within(card('DEL_SOMETHING')).getByRole('button', { name: buttonName('立即运行') }))
    expect(screen.getByText('立即真实运行「整理脚本」？')).toBeTruthy()
    expect(screen.getByText(/会真实删除文件/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: buttonName('确定') }))
    expect(onRun).toHaveBeenCalledWith(DEL_JOB, false)
  })

  it('演练确认框说明不会改动任何文件', () => {
    const job = makeJob()
    const { onRun } = renderCards([job])
    fireEvent.click(within(card('sehuatang')).getByRole('button', { name: buttonName('演练') }))
    expect(screen.getByText('演练运行「色花堂抓取」？不会提交或改动任何文件。')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: buttonName('确定') }))
    expect(onRun).toHaveBeenCalledWith(job, true)
  })

  it('上次结果用一句话显示 sehuatang 的数量', () => {
    const latest = makeRun({
      script_name: 'sehuatang',
      counts: { ...makeRun().counts, submitted: 40, title_blocked: 5, torrent_blocked: 1, skipped_seen: 20, submit_failed: 1, parse_failed: 2 },
    })
    renderCards([makeJob({ latest_run: latest })])
    expect(within(card('sehuatang')).getByText(/提交 40，标题拦 5，种子拦 1，跳过 20，失败 3/)).toBeTruthy()
  })
})
