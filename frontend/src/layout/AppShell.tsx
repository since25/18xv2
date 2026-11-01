import { DownOutlined, LogoutOutlined, MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Button, Dropdown, Layout, Menu, Space, Typography } from 'antd'
import { NavLink, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useVisualTheme } from '@/theme'
import { getNavTrail, getSelectedNavKey, NAV_GROUPS } from './navigation'

const { Content, Header, Sider } = Layout

type AppShellProps = {
  username: string
  onLogout: () => void
  children: ReactNode
}

export default function AppShell({ username, onLogout, children }: AppShellProps) {
  const { pathname } = useLocation()
  const { setMode } = useVisualTheme()
  const selected = getSelectedNavKey(pathname)
  const trail = getNavTrail(pathname)

  const userMenuItems = [
    {
      type: 'group' as const,
      label: '外观',
      children: [
        { key: 'comfort', icon: <SunOutlined />, label: '浅色' },
        { key: 'graphite', icon: <MoonOutlined />, label: '深色' },
      ],
    },
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  return (
    <Layout className="app-shell">
      <Sider width={212} className="app-sidebar">
        <div className="app-brand" aria-label="18x 整理台">
          <span>18x 整理台</span>
        </div>
        {NAV_GROUPS.map((group) => (
          <div className="app-nav-group" key={group.label}>
            <div className="app-nav-label">{group.label}</div>
            <Menu
              mode="inline"
              selectedKeys={[selected]}
              className="app-nav-menu"
              items={group.items.map((item) => ({
                key: item.key,
                icon: item.icon,
                label: <NavLink to={item.key}>{item.label}</NavLink>,
              }))}
            />
          </div>
        ))}
      </Sider>
      <Layout className="app-main">
        <Header className="app-topbar">
          <div className="app-topbar-copy">
            {trail ? <Typography.Text className="app-breadcrumb">{trail.group} / {trail.page}</Typography.Text> : null}
          </div>
          <Space wrap size={10} className="app-topbar-actions">
            <Dropdown
              trigger={['click']}
              menu={{
                items: userMenuItems,
                selectable: false,
                onClick: ({ key }) => {
                  if (key === 'comfort' || key === 'graphite') setMode(key)
                  if (key === 'logout') onLogout()
                },
              }}
            >
              <Button type="text" className="app-user-menu" aria-label={username}>
                {username}
                <DownOutlined />
              </Button>
            </Dropdown>
          </Space>
        </Header>
        <Content className="app-content">
          <div className="route-transition" key={pathname}>
            {children}
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
