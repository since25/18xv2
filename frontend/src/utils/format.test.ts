import { describe, expect, it } from 'vitest'
import { formatBytes, formatDuration, formatRelative, formatShortDateTime } from './format'

const now = new Date('2026-11-01T12:00:00+08:00')

describe('formatBytes', () => {
  it('formats byte values with binary units', () => {
    expect(formatBytes(12948331)).toBe('12.3 MB')
    expect(formatBytes(0)).toBe('-')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(2.5 * 1024 ** 4)).toBe('2.5 TB')
  })
})

describe('formatShortDateTime', () => {
  it('uses Shanghai time and omits the year for the current year', () => {
    expect(formatShortDateTime('2026-10-28T06:05:00Z', now)).toBe('10-28 14:05')
    expect(formatShortDateTime('2025-10-28T06:05:00Z', now)).toBe('2025-10-28')
    expect(formatShortDateTime(null)).toBe('-')
  })
})

describe('formatRelative', () => {
  it('formats recent values in Chinese relative time', () => {
    expect(formatRelative(new Date(now.getTime() - 180_000), now)).toBe('3 分钟前')
    expect(formatRelative(new Date(now.getTime() - 2 * 86_400_000), now)).toBe('2 天前')
  })
})

describe('formatDuration', () => {
  it('formats durations at useful precision', () => {
    expect(formatDuration(4320)).toBe('1 小时 12 分')
    expect(formatDuration(45)).toBe('45 秒')
    expect(formatDuration(754)).toBe('12 分 34 秒')
    expect(formatDuration(null)).toBe('-')
  })
})
