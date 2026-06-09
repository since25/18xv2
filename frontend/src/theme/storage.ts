import { THEME_MODES, type ThemeMode } from './types'

export const THEME_STORAGE_KEY = '18x-theme-mode'

export function normalizeThemeMode(value: unknown): ThemeMode {
  return THEME_MODES.includes(value as ThemeMode) ? (value as ThemeMode) : 'comfort'
}

export function readStoredTheme(storage: Storage = window.localStorage): ThemeMode {
  try {
    return normalizeThemeMode(storage.getItem(THEME_STORAGE_KEY))
  } catch {
    return 'comfort'
  }
}

export function writeStoredTheme(mode: ThemeMode, storage: Storage = window.localStorage) {
  try {
    storage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Private browsing and locked-down WebViews can reject storage writes.
  }
}
