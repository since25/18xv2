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

  it('MOVE 保存时提交源和目标目录', async () => {
    const job = makeJob({
      job_name: 'MOVE_SSD_CACHE_TO_DISK2',
      label: '搬运脚本',
      run_time: '01:01',
      params: { source_dir: '/mnt/cache/docker1/SSD_cache/示例源', target_dir: '/mnt/disk2/qbbtdn/示例目标' },
      site_session: null,
    })
    render(<JobSettingsDrawer job={job} open onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('目标目录'), { target: { value: '/mnt/disk2/qbbtdn/新目标' } })
    fireEvent.click(screen.getByRole('button', { name: buttonName('保存设置') }))
    await waitFor(() => expect(updateScriptJob).toHaveBeenCalled())
    const [name, body] = updateScriptJob.mock.calls[0]
    expect(name).toBe('MOVE_SSD_CACHE_TO_DISK2')
    expect(body.params).toEqual({ source_dir: '/mnt/cache/docker1/SSD_cache/示例源', target_dir: '/mnt/disk2/qbbtdn/新目标' })
    expect(screen.queryByText(/本阶段只读/)).toBeNull()
  })

  it('DEL 保存删除目录和整理任务', async () => {
    const job = {
      ...DEL_JOB,
      params: {
        delete_dirs: ['/mnt/cache/docker1/SSD_cache/甲', '/mnt/disk2/qbbtdn/乙'],
        organize_jobs: [
          { scan_root: '/mnt/cache/docker1/SSD_cache/扫甲', target_root: '/mnt/cache/docker1/SSD_cache/整甲' },
          { scan_root: '/mnt/disk2/qbbtdn/扫乙', target_root: '/mnt/disk2/qbbtdn/整乙' },
        ],
        merge_on_conflict: true,
        fix_permissions: true,
      },
    }
    render(<JobSettingsDrawer job={job} open onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByText(/关键词在「关键词」页管理/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('删除扫描目录（每行一个）'), {
      target: { value: '/mnt/cache/docker1/SSD_cache/甲\n\n  /mnt/disk2/qbbtdn/丙  \n' },
    })
    fireEvent.click(screen.getByRole('button', { name: '删除第 2 条整理任务' }))
    fireEvent.click(screen.getByLabelText('跑完修正权限'))
    fireEvent.click(screen.getByRole('button', { name: buttonName('保存设置') }))
    await waitFor(() => expect(updateScriptJob).toHaveBeenCalled())
    const [name, body] = updateScriptJob.mock.calls[0]
    expect(name).toBe('DEL_SOMETHING')
    expect(body.params).toEqual({
      delete_dirs: ['/mnt/cache/docker1/SSD_cache/甲', '/mnt/disk2/qbbtdn/丙'],
      organize_jobs: [{ scan_root: '/mnt/cache/docker1/SSD_cache/扫甲', target_root: '/mnt/cache/docker1/SSD_cache/整甲' }],
      merge_on_conflict: true,
      fix_permissions: false,
    })
  })

  it('DEL 目录校验失败时显示后端原因', async () => {
    updateScriptJob.mockRejectedValueOnce(new Error('目录不在容器已挂载的目录下（只能选 /mnt/cache/docker1/SSD_cache 之下）：/tmp/x'))
    render(<JobSettingsDrawer job={DEL_JOB} open onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: buttonName('保存设置') }))
    expect(await screen.findByText(/目录不在容器已挂载的目录下/)).toBeTruthy()
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
