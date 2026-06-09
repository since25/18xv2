import { useContext } from 'react'
import { VisualThemeContext } from './VisualThemeContext'

export function useVisualTheme() {
  const value = useContext(VisualThemeContext)
  if (!value) {
    throw new Error('useVisualTheme must be used inside VisualThemeProvider')
  }
  return value
}
