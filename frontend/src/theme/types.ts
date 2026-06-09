export const THEME_MODES = ['comfort', 'graphite'] as const

export type ThemeMode = (typeof THEME_MODES)[number]

export type ThemePalette = {
  mode: ThemeMode
  brand: string
  bgLayout: string
  bgContainer: string
  bgElevated: string
  bgMuted: string
  border: string
  text: string
  textSecondary: string
  sidebarBg: string
  sidebarText: string
  sidebarMuted: string
  headerBg: string
  focus: string
}
