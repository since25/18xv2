import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEL_JOB, buttonName, makeJob } from './testData'

const updateScriptJob = vi.fn()
const updateSiteSession = vi.fn()

vi.mock('@/api/scriptJobs', () => ({
  updateScriptJob: (...args: unknown[]) => updateScriptJob(...args),
  updateSiteSession: (...args: unknown[]) => updateSiteSession(...args),
}))

const { default: JobSettingsDrawer } = await import('./JobSettingsDrawer')

describe('JobSettingsDrawer', () => {
  beforeEach(() => {
    updateScriptJob.mockImplementation((_name: string, body: object) => Promise.resolve({ ...makeJob(), ...body }))
    updateSiteSession.mockResolvedValue({ configured: true, updated_at: '2026-11-25T12:00:00Z' })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('保存 sehuatang 设置时提交页数等参数', async () => {
    const onSaved = vi.fn()
    render(<JobSettingsDrawer job={makeJob()} open onClose={vi.fn()} onSaved={onSaved} />)
    fireEvent.change(screen.getByLabelText('抓几页'), { target: { value: '6' } })
    fireEvent.click(screen.getByRole('button', { name: buttonName('保存设置') }))
    await waitFor(() => expect(updateScriptJob).toHaveBeenCalled())
    const [name, body] = updateScriptJob.mock.calls[0]
    expect(name).toBe('sehuatang')
    expect(body).toMatchObject({ enabled: true, run_time: '01:28', executor: '18x', params: { pages: 6, qb_category: '国产BT' } })
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('保存失败时显示后端返回的中文原因', async () => {
    updateScriptJob.mockRejectedValueOnce(new Error('运行时间格式应为 HH:MM，例如 01:28'))
    render(<JobSettingsDrawer job={makeJob()} open onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: buttonName('保存设置') }))
    expect(await screen.findByText(/运行时间格式应为 HH:MM/)).toBeTruthy()
  })

  it('不能在 18x 执行的脚本禁用执行方并提示', () => {
    render(<JobSettingsDrawer job={{ ...DEL_JOB, runnable: false, executor: 'unraid' }} open onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByText('尚未支持在 18x 执行')).toBeTruthy()
    expect(screen.queryByLabelText('抓几页')).toBeNull()
  })

  it('站点 cookie 保存后输入框清空且页面不出现旧 cookie', async () => {
    const onSaved = vi.fn()
    render(<JobSettingsDrawer job={makeJob()} open onClose={vi.fn()} onSaved={onSaved} />)
    expect(screen.getByText(/已设置，最后更新/)).toBeTruthy()
    const cookieInput = screen.getByLabelText('站点 cookie') as HTMLTextAreaElement
    const uaInput = screen.getByLabelText('浏览器 User-Agent') as HTMLInputElement
    fireEvent.change(cookieInput, { target: { value: 'cf_clearance=SECRET-COOKIE' } })
    fireEvent.change(uaInput, { target: { value: 'Mozilla/5.0 Test Agent' } })
    fireEvent.click(screen.getByRole('button', { name: buttonName('保存 cookie') }))
    await waitFor(() => expect(updateSiteSession).toHaveBeenCalledWith('cf_clearance=SECRET-COOKIE', 'Mozilla/5.0 Test Agent'))
    await waitFor(() => expect(cookieInput.value).toBe(''))
    expect(uaInput.value).toBe('')
    expect(document.body.textContent).not.toContain('SECRET-COOKIE')
    expect(onSaved).toHaveBeenCalled()
  })

  it('未设置 cookie 时显示未设置', () => {
    render(<JobSettingsDrawer job={makeJob({ site_session: { configured: false, updated_at: null } })} open onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByText('未设置')).toBeTruthy()
  })
})
