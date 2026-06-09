import { describe, expect, it } from 'vitest'
import { buildAntdTheme } from './antdTheme'

describe('buildAntdTheme', () => {
  it('uses purple as the shared primary brand color', () => {
    expect(buildAntdTheme('comfort').token?.colorPrimary).toBe('#8b5cf6')
    expect(buildAntdTheme('graphite').token?.colorPrimary).toBe('#8b5cf6')
  })

  it('keeps comfort brighter than graphite', () => {
    const comfort = buildAntdTheme('comfort').token
    const graphite = buildAntdTheme('graphite').token
    expect(comfort?.colorBgLayout).toBe('#ece8f2')
    expect(graphite?.colorBgLayout).toBe('#202027')
  })
})
