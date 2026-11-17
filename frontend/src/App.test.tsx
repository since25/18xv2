import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { VisualThemeProvider } from './theme'

// 用真实的 api/client，只替换 fetch，按地址返回预设结果
type Route = (path: string, init?: RequestInit) => Response | undefined

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const emptyList = { items: [], total: 0 }

function renderApp(url: string) {
  window.history.pushState({}, '', url)
  return render(
    <VisualThemeProvider>
      <App />
    </VisualThemeProvider>,
  )
}

describe('App 登录过期处理', () => {
  let route: Route

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn((input: string, init?: RequestInit) => {
      const path = String(input).replace(/^\/api/, '')
      return Promise.resolve(route(path, init) ?? jsonResponse(200, emptyList))
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    window.history.pushState({}, '', '/')
  })

  it('已登录时接口返回 401：回到登录页、只提示一次，重新登录后跳回原地址', async () => {
    let expired = true
    route = (path) => {
      if (path === '/auth/me') return jsonResponse(200, { username: 'wang' })
      if (path === '/auth/login') return jsonResponse(200, { username: 'wang' })
      // 页面打开时同时发出的两个请求都返回 401
      if (expired) return jsonResponse(401, { detail: 'Not authenticated' })
      return undefined
    }

    renderApp('/nodes?import_id=3')

    expect(await screen.findByRole('heading', { name: '管理员登录' })).toBeInTheDocument()
    expect(await screen.findByText('登录已过期，请重新登录')).toBeInTheDocument()
    // 等所有 401 都返回后再确认只提示了一次
    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([input]) => String(input))
      expect(calls.filter((item) => item.startsWith('/api/imports')).length).toBeGreaterThanOrEqual(2)
    })
    expect(screen.getAllByText('登录已过期，请重新登录')).toHaveLength(1)
    expect(window.location.pathname).toBe('/login')

    expired = false
    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText('请输入初始密码或当前密码'), 'secret')
    await user.click(screen.getByRole('button', { name: /登录进入系统/ }))

    await waitFor(() => expect(window.location.pathname + window.location.search).toBe('/nodes?import_id=3'))
    expect(await screen.findByRole('heading', { name: '目录树内容' })).toBeInTheDocument()
  })

  it('登录接口返回 401 时仍显示原错误，不出现“登录已过期”', async () => {
    route = (path) => {
      if (path === '/auth/me') return jsonResponse(401, { detail: 'Not authenticated' })
      if (path === '/auth/login') return jsonResponse(401, { detail: '用户名或密码错误' })
      return undefined
    }

    renderApp('/login')

    const user = userEvent.setup()
    await user.type(await screen.findByPlaceholderText('请输入初始密码或当前密码'), 'wrong')
    await user.click(screen.getByRole('button', { name: /登录进入系统/ }))

    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
    expect(screen.queryByText('登录已过期，请重新登录')).not.toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')
  })
})
