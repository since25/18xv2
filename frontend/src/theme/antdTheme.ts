import { theme, type ThemeConfig } from 'antd'
import { THEME_PALETTES } from './palettes'
import type { ThemeMode } from './types'

export function buildAntdTheme(mode: ThemeMode): ThemeConfig {
  const palette = THEME_PALETTES[mode]
  return {
    algorithm: mode === 'graphite' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: palette.brand,
      colorBgLayout: palette.bgLayout,
      colorBgContainer: palette.bgContainer,
      colorBgElevated: palette.surfaceElevated,
      colorBorder: palette.border,
      colorText: palette.text,
      colorTextSecondary: palette.textSecondary,
      borderRadius: 6,
      boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.03), 0 0 0 1px var(--app-border)',
      boxShadowSecondary: '0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.08)',
      controlHeight: 34,
      motionDurationFast: '0.15s',
      motionDurationMid: '0.2s',
    },
    components: {
      Button: { borderRadius: 6, controlHeight: 34 },
      Card: { borderRadiusLG: 8, boxShadowTertiary: '0 1px 3px 0 rgba(0, 0, 0, 0.03), 0 0 0 1px var(--app-border)', headerBg: palette.bgContainer },
      Layout: { bodyBg: palette.bgLayout, headerBg: palette.bgContainer, siderBg: palette.bgContainer },
      Menu: {
        itemBg: palette.bgContainer,
        subMenuItemBg: palette.bgContainer,
        itemColor: palette.textSecondary,
        itemSelectedBg: palette.brandSubtle,
        itemSelectedColor: palette.brand,
      },
      Table: {
        headerBg: palette.bgMuted,
        rowHoverBg: palette.bgMuted,
      },
    },
  }
}
