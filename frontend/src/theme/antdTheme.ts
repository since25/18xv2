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
      colorBgElevated: palette.bgElevated,
      colorBorder: palette.border,
      colorText: palette.text,
      colorTextSecondary: palette.textSecondary,
      borderRadius: 10,
      boxShadow: 'none',
      boxShadowSecondary: 'none',
      controlHeight: 34,
      motionDurationFast: '0.15s',
      motionDurationMid: '0.2s',
    },
    components: {
      Button: { borderRadius: 9, controlHeight: 34 },
      Card: { borderRadiusLG: 12, boxShadowTertiary: 'none', headerBg: palette.bgContainer },
      Layout: { bodyBg: palette.bgLayout, headerBg: palette.headerBg, siderBg: palette.sidebarBg },
      Menu: {
        darkItemBg: palette.sidebarBg,
        darkSubMenuItemBg: palette.sidebarBg,
        darkItemColor: palette.sidebarMuted,
        darkItemSelectedBg: 'rgba(139, 92, 246, 0.18)',
        darkItemSelectedColor: palette.sidebarText,
      },
      Table: {
        headerBg: palette.bgMuted,
        rowHoverBg: mode === 'graphite' ? 'rgba(139, 92, 246, 0.12)' : 'rgba(139, 92, 246, 0.08)',
      },
    },
  }
}
