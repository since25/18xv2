import type { ThemeMode, ThemePalette } from './types'

export const BRAND_PURPLE = '#8b5cf6'

export const THEME_PALETTES: Record<ThemeMode, ThemePalette> = {
  comfort: {
    mode: 'comfort',
    brand: BRAND_PURPLE,
    bgLayout: '#ece8f2',
    bgContainer: '#f8f6fb',
    bgElevated: '#ffffff',
    bgMuted: '#f0edf6',
    border: 'rgba(44, 38, 58, 0.14)',
    text: '#292337',
    textSecondary: '#6f687c',
    sidebarBg: '#15131c',
    sidebarText: '#f7f2ff',
    sidebarMuted: '#aaa4b8',
    headerBg: 'rgba(248, 246, 251, 0.92)',
    focus: 'rgba(139, 92, 246, 0.42)',
  },
  graphite: {
    mode: 'graphite',
    brand: BRAND_PURPLE,
    bgLayout: '#202027',
    bgContainer: '#2a2a33',
    bgElevated: '#30303a',
    bgMuted: '#24242d',
    border: 'rgba(255, 255, 255, 0.12)',
    text: '#f3eff9',
    textSecondary: '#aaa5b5',
    sidebarBg: '#14131a',
    sidebarText: '#f7f2ff',
    sidebarMuted: '#aaa4b8',
    headerBg: 'rgba(32, 32, 39, 0.92)',
    focus: 'rgba(139, 92, 246, 0.5)',
  },
}
