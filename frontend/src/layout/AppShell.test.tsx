import { MemoryRouter } from 'react-router-dom'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { VisualThemeProvider } from '@/theme'
import AppShell from './AppShell'

describe('AppShell', () => {
  it('renders grouped navigation and lets the user switch themes', async () => {
    render(
      <VisualThemeProvider>
        <MemoryRouter initialEntries={['/dedupe']}>
          <AppShell username="wang" onLogout={() => undefined}>
            <main>Page content</main>
          </AppShell>
        </MemoryRouter>
      </VisualThemeProvider>,
    )

    expect(screen.getByText('18x 整理台')).toBeInTheDocument()
    expect(screen.getByText('Workflow')).toBeInTheDocument()
    expect(screen.getByText('文件去重')).toBeInTheDocument()
    expect(screen.getByText('Page content')).toBeInTheDocument()

    const themeControl = screen.getByLabelText('主题模式')
    await userEvent.click(within(themeControl).getByText('墨灰'))

    expect(document.documentElement).toHaveAttribute('data-theme', 'graphite')
  })
})
