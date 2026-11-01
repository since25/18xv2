import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/client', () => ({ api }))

import AuthCenterPage from './AuthCenterPage'
import OpenAuthPage from './OpenAuthPage'
import QrLoginPage from './QrLoginPage'
import SettingsPage from './SettingsPage'
import LoginPage from './LoginPage'

function renderPage(page: ReactNode) {
  return render(<MemoryRouter>{page}</MemoryRouter>)
}

describe('系统组与登录页冒烟渲染', () => {
  beforeEach(() => {
    api.get.mockResolvedValue({ items: [], records: [], clients: [], cookies: [], token_status: 'missing' })
    api.post.mockResolvedValue({ records: [], clients: [], cookies: [], status: 0, qr_image_url: '', session_id: 'smoke' })
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  const cases: Array<[string, ReactNode, string]> = [
    ['授权中心', <AuthCenterPage />, '授权中心'],
    ['Open API 扫码授权', <OpenAuthPage />, 'Open API 扫码授权'],
    ['扫码登录', <QrLoginPage />, '扫码登录'],
    ['系统状态', <SettingsPage />, '系统状态'],
    ['登录', <LoginPage defaultUsername="admin" loading={false} error={null} onSubmit={vi.fn()} />, '登录'],
  ]

  it.each(cases)('渲染 %s 的页面标题', async (_name, page, title) => {
    renderPage(page)
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
  })
})
