import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { VisualThemeProvider } from '@/theme'
import AppShell from './AppShell'

describe('AppShell', () => {
  it('renders the Chinese shell and lets the user switch themes', async () => {
    const onLogout = vi.fn()
    render(
      <VisualThemeProvider>
        <MemoryRouter initialEntries={['/dedupe']}>
          <AppShell username="wang" onLogout={onLogout}>
            <main>Page content</main>
          </AppShell>
        </MemoryRouter>
      </VisualThemeProvider>,
    )

    expect(screen.getByText('18x 整理台')).toBeInTheDocument()
    expect(screen.getByText('流程')).toBeInTheDocument()
    expect(screen.getByText('文件去重')).toBeInTheDocument()
    expect(screen.getByText('流程 / 文件去重')).toBeInTheDocument()
    expect(screen.queryByText('Admin workspace')).not.toBeInTheDocument()
    expect(screen.getByText('Page content')).toBeInTheDocument()

    const user = userEvent.setup()
    const userMenu = screen.getByRole('button', { name: 'wang' })
    expect(userMenu).not.toHaveClass('app-user-chip')
    await user.click(userMenu)
    await user.click(screen.getByText('深色'))

    expect(document.documentElement).toHaveAttribute('data-theme', 'graphite')
    await user.click(screen.getByRole('button', { name: 'wang' }))
    await user.click(screen.getByText('退出登录'))

    expect(onLogout).toHaveBeenCalledOnce()
  })
})
