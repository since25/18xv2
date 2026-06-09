import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { buildAntdTheme } from './antdTheme'
import { readStoredTheme, writeStoredTheme } from './storage'
import type { ThemeMode } from './types'

type VisualThemeContextValue = {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

const VisualThemeContext = createContext<VisualThemeContextValue | null>(null)

export function VisualThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => readStoredTheme())

  useEffect(() => {
    document.documentElement.dataset.theme = mode
    writeStoredTheme(mode)
  }, [mode])

  const contextValue = useMemo(() => ({ mode, setMode }), [mode])

  return (
    <VisualThemeContext.Provider value={contextValue}>
      <ConfigProvider locale={zhCN} theme={buildAntdTheme(mode)}>
        {children}
      </ConfigProvider>
    </VisualThemeContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useVisualTheme() {
  const value = useContext(VisualThemeContext)
  if (!value) {
    throw new Error('useVisualTheme must be used inside VisualThemeProvider')
  }
  return value
}
