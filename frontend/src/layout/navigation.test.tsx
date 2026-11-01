import { describe, expect, it } from 'vitest'
import { getNavTrail, getSelectedNavKey } from './navigation'

describe('getSelectedNavKey', () => {
  it('matches exact and nested routes without selecting prefix siblings', () => {
    expect(getSelectedNavKey('/plans')).toBe('/plans')
    expect(getSelectedNavKey('/plans/123')).toBe('/plans')
    expect(getSelectedNavKey('/plans-old')).toBe('')
  })
})

describe('getNavTrail', () => {
  it('returns translated group and page labels', () => {
    expect(getNavTrail('/downloader')).toEqual({ group: '流程', page: '下载器' })
  })
})
