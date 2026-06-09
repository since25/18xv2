import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  THEME_STORAGE_KEY,
  normalizeThemeMode,
  readStoredTheme,
  writeStoredTheme,
} from './storage'

function storageWith(seed?: Record<string, string>) {
  const values = new Map(Object.entries(seed ?? {}))
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  } as unknown as Storage
}

describe('theme storage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('normalizes unknown values to comfort', () => {
    expect(normalizeThemeMode(null)).toBe('comfort')
    expect(normalizeThemeMode('graphite')).toBe('graphite')
    expect(normalizeThemeMode('solarized')).toBe('comfort')
  })

  it('reads comfort when storage is empty or throws', () => {
    expect(readStoredTheme(storageWith())).toBe('comfort')
    const brokenStorage = {
      getItem: () => {
        throw new Error('blocked')
      },
    } as unknown as Storage
    expect(readStoredTheme(brokenStorage)).toBe('comfort')
  })

  it('writes a valid theme mode', () => {
    const storage = storageWith()
    writeStoredTheme('graphite', storage)
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe('graphite')
  })

  it('reads comfort when no browser window is available', () => {
    vi.stubGlobal('window', undefined)
    expect(() => readStoredTheme()).not.toThrow()
    expect(readStoredTheme()).toBe('comfort')
  })

  it('ignores writes when no browser window is available', () => {
    vi.stubGlobal('window', undefined)
    expect(() => writeStoredTheme('graphite')).not.toThrow()
  })
})
