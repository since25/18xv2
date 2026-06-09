import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { buildAntdTheme } from './antdTheme'
import { readStoredTheme, writeStoredTheme } from './storage'
import { VisualThemeContext } from './VisualThemeContext'
import type { ThemeMode } from './types'

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
