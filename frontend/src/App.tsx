import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Spin, Typography, message } from 'antd'
import { ApiError, api } from './api/client'
import type { AuthMeResponse, LoginResponse } from './api/types'
import AppShell from './layout/AppShell'
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
import WhitelistBatchPage from './pages/WhitelistBatchPage'
import ReviewIntakePage from './pages/ReviewIntakePage'
import FileDedupePage from './pages/FileDedupePage'
import AuthCenterPage from './pages/AuthCenterPage'
import OpenAuthPage from './pages/OpenAuthPage'
import QrLoginPage from './pages/QrLoginPage'
import LoginPage from './pages/LoginPage'
import NodesPage from './pages/NodesPage'

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
      <AppShell username={auth.username} onLogout={() => void handleLogout()}>
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
          <Route path="/whitelist-batch" element={<WhitelistBatchPage />} />
          <Route path="/review-intake" element={<ReviewIntakePage />} />
          <Route path="/dedupe" element={<FileDedupePage />} />
          <Route path="/magnet-tasks" element={<MagnetTasksPage />} />
          <Route path="/auth-center" element={<AuthCenterPage />} />
          <Route path="/auth-center/open-api-qr" element={<OpenAuthPage />} />
          <Route path="/auth-center/qr-login" element={<QrLoginPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/imports" replace />} />
        </Routes>
      </AppShell>
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
