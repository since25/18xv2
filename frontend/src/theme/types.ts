export const THEME_MODES = ['comfort', 'graphite'] as const

export type ThemeMode = (typeof THEME_MODES)[number]

export type ThemePalette = {
  mode: ThemeMode
  brand: string
  bgLayout: string
  bgContainer: string
  surfaceElevated: string
  bgMuted: string
  border: string
  borderStrong: string
  text: string
  textSecondary: string
  brandSubtle: string
  success: string
  successBg: string
  warning: string
  warningBg: string
  danger: string
  dangerBg: string
  focus: string
}
