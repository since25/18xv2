import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, NavLink, useNavigate } from 'react-router-dom'
import { Button, Layout, Menu, Space, Spin, Typography, message } from 'antd'
import {
  InboxOutlined,
  TagsOutlined,
  FireOutlined,
  ApartmentOutlined,
  OrderedListOutlined,
  HistoryOutlined,
  SettingOutlined,
  RadarChartOutlined,
  ScanOutlined,
  CloudDownloadOutlined,
  SafetyCertificateOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { ApiError, api } from './api/client'
import type { AuthMeResponse, LoginResponse } from './api/types'
import ImportsPage from './pages/ImportsPage'
import KeywordsPage from './pages/KeywordsPage'
import HitsPage from './pages/HitsPage'
import OrganizeTasksPage from './pages/OrganizeTasksPage'
import PlansPage from './pages/PlansPage'
import PlanDetailPage from './pages/PlanDetailPage'
import ExecutorPage from './pages/ExecutorPage'
import SettingsPage from './pages/SettingsPage'
import KeywordExtractorPage from './pages/KeywordExtractorPage'
import KeywordDuplicatesPage from './pages/KeywordDuplicatesPage'
import MagnetTasksPage from './pages/MagnetTasksPage'
import AuthCenterPage from './pages/AuthCenterPage'
import OpenAuthPage from './pages/OpenAuthPage'
import QrLoginPage from './pages/QrLoginPage'
import LoginPage from './pages/LoginPage'
import NodesPage from './pages/NodesPage'

const { Sider, Content, Header } = Layout

const NAV = [
  { key: '/imports',        label: '导入批次',   icon: <InboxOutlined /> },
  { key: '/nodes',          label: '目录内容',   icon: <ApartmentOutlined /> },
  { key: '/extractor',      label: '关键词提取', icon: <RadarChartOutlined /> },
  { key: '/keywords',       label: '关键词',     icon: <TagsOutlined /> },
  { key: '/keyword-duplicates', label: '重复词扫描', icon: <ScanOutlined /> },
  { key: '/hits',           label: '命中重建',   icon: <FireOutlined /> },
  { key: '/organize-tasks', label: '整理任务',   icon: <ApartmentOutlined /> },
  { key: '/plans',          label: '整理计划',   icon: <OrderedListOutlined /> },
  { key: '/executor',       label: '执行日志',   icon: <HistoryOutlined /> },
  { key: '/magnet-tasks',   label: '磁力下载',   icon: <CloudDownloadOutlined /> },
  { key: '/auth-center',    label: '授权中心',   icon: <SafetyCertificateOutlined /> },
  { key: '/settings',       label: '系统状态',   icon: <SettingOutlined /> },
]

function NavMenu() {
  const { pathname } = useLocation()
  const selected = NAV.find((n) => pathname.startsWith(n.key))?.key ?? ''
  return (
    <Menu
      theme="dark"
      mode="inline"
      selectedKeys={[selected]}
      style={{ borderRight: 0, marginTop: 8 }}
      items={NAV.map((n) => ({
        key: n.key,
        icon: n.icon,
        label: <NavLink to={n.key}>{n.label}</NavLink>,
      }))}
    />
  )
}

type AuthState =
  | { status: 'loading'; username: null }
  | { status: 'authenticated'; username: string }
  | { status: 'unauthenticated'; username: null }

function LoadingScreen() {
  return (
    <div className="app-loading">
      <Spin size="large" />
      <Typography.Text type="secondary">正在检查登录状态…</Typography.Text>
    </div>
  )
}

function AppRoutes() {
  const navigate = useNavigate()
  const location = useLocation()
  const [auth, setAuth] = useState<AuthState>({ status: 'loading', username: null })
  const [submitting, setSubmitting] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)
  const [messageApi, contextHolder] = message.useMessage()

  useEffect(() => {
    let cancelled = false

    async function loadMe() {
      try {
        const profile = await api.get<AuthMeResponse>('/auth/me')
        if (!cancelled) {
          setAuth({ status: 'authenticated', username: profile.username })
        }
      } catch (error) {
        if (!cancelled) {
          if (error instanceof ApiError && error.status === 401) {
            setAuth({ status: 'unauthenticated', username: null })
          } else {
            setAuth({ status: 'unauthenticated', username: null })
            setLoginError(error instanceof Error ? error.message : '登录状态检查失败')
          }
        }
      }
    }

    void loadMe()
    return () => {
      cancelled = true
    }
  }, [])

  const handleLogin = async (values: { username: string; password: string }) => {
    setSubmitting(true)
    setLoginError(null)
    try {
      const payload = await api.post<LoginResponse>('/auth/login', values)
      setAuth({ status: 'authenticated', username: payload.username })
      const redirectTo =
        location.state && typeof location.state === 'object' && 'from' in location.state
          ? String(location.state.from || '/imports')
          : '/imports'
      navigate(redirectTo, { replace: true })
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleLogout = async () => {
    try {
      await api.post('/auth/logout')
    } finally {
      setAuth({ status: 'unauthenticated', username: null })
      setLoginError(null)
      void messageApi.success('已退出登录')
      navigate('/login', { replace: true })
    }
  }

  if (auth.status === 'loading') {
    return (
      <>
        {contextHolder}
        <LoadingScreen />
      </>
    )
  }

  if (auth.status === 'unauthenticated') {
    return (
      <>
        {contextHolder}
        <Routes>
          <Route
            path="/login"
            element={
              <LoginPage
                defaultUsername="wang"
                loading={submitting}
                error={loginError}
                onSubmit={handleLogin}
              />
            }
          />
          <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname }} />} />
        </Routes>
      </>
    )
  }

  return (
    <>
      {contextHolder}
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          width={170}
          theme="dark"
          style={{ position: 'fixed', height: '100vh', left: 0, top: 0, zIndex: 10, overflow: 'auto' }}
        >
          <div style={{ padding: '14px 16px', color: '#fff', fontWeight: 700, fontSize: 15, borderBottom: '1px solid rgba(255,255,255,.1)' }}>
            18x 整理台
          </div>
          <NavMenu />
        </Sider>
        <Layout style={{ marginLeft: 170 }}>
          <Header
            style={{
              height: 'auto',
              minHeight: 64,
              padding: '12px 24px',
              background: 'rgba(250, 246, 239, 0.88)',
              borderBottom: '1px solid rgba(132, 121, 105, 0.16)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              position: 'sticky',
              top: 0,
              zIndex: 5,
              backdropFilter: 'blur(10px)',
            }}
          >
            <div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                18x 管理台
              </Typography.Title>
              <Typography.Text type="secondary">已启用管理员登录保护</Typography.Text>
            </div>
            <Space wrap size={12}>
              <Space size={6}>
                <UserOutlined />
                <Typography.Text>{auth.username}</Typography.Text>
              </Space>
              <Button icon={<LogoutOutlined />} onClick={() => void handleLogout()}>
                退出登录
              </Button>
            </Space>
          </Header>
          <Content style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
            <Routes>
              <Route path="/login" element={<Navigate to="/imports" replace />} />
              <Route path="/" element={<Navigate to="/imports" replace />} />
              <Route path="/imports" element={<ImportsPage />} />
              <Route path="/nodes" element={<NodesPage />} />
              <Route path="/extractor" element={<KeywordExtractorPage />} />
              <Route path="/keywords" element={<KeywordsPage />} />
              <Route path="/keyword-duplicates" element={<KeywordDuplicatesPage />} />
              <Route path="/hits" element={<HitsPage />} />
              <Route path="/organize-tasks" element={<OrganizeTasksPage />} />
              <Route path="/plans" element={<PlansPage />} />
              <Route path="/plans/:id" element={<PlanDetailPage />} />
              <Route path="/executor" element={<ExecutorPage />} />
              <Route path="/magnet-tasks" element={<MagnetTasksPage />} />
              <Route path="/auth-center" element={<AuthCenterPage />} />
              <Route path="/auth-center/open-api-qr" element={<OpenAuthPage />} />
              <Route path="/auth-center/qr-login" element={<QrLoginPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/imports" replace />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
