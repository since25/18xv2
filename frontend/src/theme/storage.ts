import { THEME_MODES, type ThemeMode } from './types'

export const THEME_STORAGE_KEY = '18x-theme-mode'

export function normalizeThemeMode(value: unknown): ThemeMode {
  return THEME_MODES.includes(value as ThemeMode) ? (value as ThemeMode) : 'comfort'
}

function resolveThemeStorage(storage?: Storage): Storage | undefined {
  if (storage) {
    return storage
  }
  if (typeof window === 'undefined') {
    return undefined
  }
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

export function readStoredTheme(storage?: Storage): ThemeMode {
  const resolvedStorage = resolveThemeStorage(storage)
  if (!resolvedStorage) {
    return 'comfort'
  }
  try {
    return normalizeThemeMode(resolvedStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return 'comfort'
  }
}

export function writeStoredTheme(mode: ThemeMode, storage?: Storage) {
  const resolvedStorage = resolveThemeStorage(storage)
  if (!resolvedStorage) {
    return
  }
  try {
    resolvedStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Private browsing and locked-down WebViews can reject storage writes.
  }
}
