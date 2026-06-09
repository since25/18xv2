import { createContext } from 'react'
import type { ThemeMode } from './types'

export type VisualThemeContextValue = {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
}

export const VisualThemeContext = createContext<VisualThemeContextValue | null>(null)
