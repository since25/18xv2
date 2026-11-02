import {
  ApartmentOutlined,
  CloudDownloadOutlined,
  FireOutlined,
  HistoryOutlined,
  InboxOutlined,
  OrderedListOutlined,
  PlaySquareOutlined,
  RadarChartOutlined,
  SafetyCertificateOutlined,
  ScanOutlined,
  SettingOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

export type NavItem = {
  key: string
  label: string
  icon: ReactNode
}

export type NavGroup = {
  label: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: '数据',
    items: [
      { key: '/imports', label: '导入批次', icon: <InboxOutlined /> },
      { key: '/nodes', label: '目录内容', icon: <ApartmentOutlined /> },
      { key: '/extractor', label: '关键词提取', icon: <RadarChartOutlined /> },
      { key: '/keywords', label: '关键词', icon: <TagsOutlined /> },
      { key: '/keyword-duplicates', label: '重复词扫描', icon: <ScanOutlined /> },
      { key: '/hits', label: '命中重建', icon: <FireOutlined /> },
    ],
  },
  {
    label: '流程',
    items: [
      { key: '/organize-tasks', label: '整理任务', icon: <ApartmentOutlined /> },
      { key: '/plans', label: '整理计划', icon: <OrderedListOutlined /> },
      { key: '/executor', label: '执行日志', icon: <HistoryOutlined /> },
      { key: '/whitelist-batch', label: '白名单批处理', icon: <TagsOutlined /> },
      { key: '/review-intake', label: '待审核', icon: <InboxOutlined /> },
      { key: '/emby-media-actions', label: 'Emby 动作', icon: <PlaySquareOutlined /> },
      { key: '/dedupe', label: '文件去重', icon: <SafetyCertificateOutlined /> },
      { key: '/magnet-tasks', label: '磁力下载', icon: <CloudDownloadOutlined /> },
      { key: '/downloader', label: '下载器', icon: <CloudDownloadOutlined /> },
      { key: '/jellyfin', label: 'Jellyfin', icon: <PlaySquareOutlined /> },
    ],
  },
  {
    label: '系统',
    items: [
      { key: '/auth-center', label: '授权中心', icon: <SafetyCertificateOutlined /> },
      { key: '/settings', label: '系统状态', icon: <SettingOutlined /> },
    ],
  },
]

export const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items)

export function getSelectedNavKey(pathname: string) {
  return (
    NAV_ITEMS.slice().sort((a, b) => b.key.length - a.key.length).find(
      (item) => pathname === item.key || pathname.startsWith(`${item.key}/`),
    )?.key ?? ''
  )
}

export function getNavTrail(pathname: string): { group: string; page: string } | null {
  const key = getSelectedNavKey(pathname)
  if (!key) return null
  const group = NAV_GROUPS.find((item) => item.items.some((navItem) => navItem.key === key))
  const page = NAV_ITEMS.find((item) => item.key === key)
  return group && page ? { group: group.label, page: page.label } : null
}
