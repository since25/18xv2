import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { useVisualTheme, VisualThemeProvider } from './VisualThemeProvider'
import { THEME_STORAGE_KEY } from './storage'

function createTestStorage() {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, value),
  } as Storage
}

const testStorage = createTestStorage()

Object.defineProperty(window, 'localStorage', {
  value: testStorage,
  configurable: true,
})

Object.defineProperty(globalThis, 'localStorage', {
  value: testStorage,
  configurable: true,
})

function ThemeProbe() {
  const { mode, setMode } = useVisualTheme()
  return (
    <>
      <div data-testid="mode">{mode}</div>
      <button onClick={() => setMode('graphite')}>Graphite</button>
    </>
  )
}

describe('VisualThemeProvider', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('starts in comfort mode and persists graphite after switching', async () => {
    render(
      <VisualThemeProvider>
        <ThemeProbe />
      </VisualThemeProvider>,
    )

    expect(screen.getByTestId('mode')).toHaveTextContent('comfort')
    expect(document.documentElement).toHaveAttribute('data-theme', 'comfort')

    await userEvent.click(screen.getByRole('button', { name: 'Graphite' }))

    expect(screen.getByTestId('mode')).toHaveTextContent('graphite')
    expect(document.documentElement).toHaveAttribute('data-theme', 'graphite')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('graphite')
  })
})
