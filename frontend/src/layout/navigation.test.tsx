import { describe, expect, it } from 'vitest'
import { getSelectedNavKey } from './navigation'

describe('getSelectedNavKey', () => {
  it('matches exact and nested routes without selecting prefix siblings', () => {
    expect(getSelectedNavKey('/plans')).toBe('/plans')
    expect(getSelectedNavKey('/plans/123')).toBe('/plans')
    expect(getSelectedNavKey('/plans-old')).toBe('')
  })
})
