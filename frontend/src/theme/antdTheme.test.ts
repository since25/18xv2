import { describe, expect, it } from 'vitest'
import { buildAntdTheme } from './antdTheme'

describe('buildAntdTheme', () => {
  it('uses a blue primary brand color for each theme mode', () => {
    expect(buildAntdTheme('comfort').token?.colorPrimary).toBe('#0284c7')
    expect(buildAntdTheme('graphite').token?.colorPrimary).toBe('#38bdf8')
  })

  it('uses compact radii and card styling', () => {
    const config = buildAntdTheme('comfort')
    expect(config.token?.borderRadius).toBe(6)
    expect(config.components?.Card?.borderRadiusLG).toBe(8)
  })

  it('does not contain the retired legacy palette', () => {
    const retiredHex = ['8', 'b5cf6'].join('')
    const retiredRgb = ['139', '92', '246'].join(', ')
    expect(JSON.stringify(buildAntdTheme('comfort'))).not.toContain(retiredHex)
    expect(JSON.stringify(buildAntdTheme('comfort'))).not.toContain(retiredRgb)
    expect(JSON.stringify(buildAntdTheme('graphite'))).not.toContain(retiredHex)
    expect(JSON.stringify(buildAntdTheme('graphite'))).not.toContain(retiredRgb)
  })
})
