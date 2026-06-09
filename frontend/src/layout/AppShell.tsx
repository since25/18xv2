import { LogoutOutlined, MoonOutlined, SunOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Layout, Menu, Segmented, Space, Typography } from 'antd'
import { NavLink, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useVisualTheme, type ThemeMode } from '@/theme'
import { getSelectedNavKey, NAV_GROUPS } from './navigation'

const { Content, Header, Sider } = Layout

type AppShellProps = {
  username: string
  onLogout: () => void
  children: ReactNode
}

export default function AppShell({ username, onLogout, children }: AppShellProps) {
  const { pathname } = useLocation()
  const { mode, setMode } = useVisualTheme()
  const selected = getSelectedNavKey(pathname)

  return (
    <Layout className="app-shell">
      <Sider width={212} className="app-sidebar">
        <div className="app-brand" aria-label="18x 整理台">
          <span className="app-brand-mark">18</span>
          <span>18x 整理台</span>
        </div>
        {NAV_GROUPS.map((group) => (
          <div className="app-nav-group" key={group.label}>
            <div className="app-nav-label">{group.label}</div>
            <Menu
              theme="dark"
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
            <Typography.Text className="app-eyebrow">Admin workspace</Typography.Text>
            <Typography.Title level={4} className="app-title">
              18x 管理台
            </Typography.Title>
          </div>
          <Space wrap size={10} className="app-topbar-actions">
            <Segmented<ThemeMode>
              aria-label="主题模式"
              value={mode}
              onChange={(value) => setMode(value)}
              options={[
                { label: '护眼', value: 'comfort', icon: <SunOutlined /> },
                { label: '墨灰', value: 'graphite', icon: <MoonOutlined /> },
              ]}
            />
            <Space size={6} className="app-user-chip">
              <UserOutlined />
              <Typography.Text>{username}</Typography.Text>
            </Space>
            <Button icon={<LogoutOutlined />} onClick={onLogout}>
              退出登录
            </Button>
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
