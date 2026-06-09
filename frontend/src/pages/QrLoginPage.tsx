import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from 'antd'
import { QrcodeOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import PageScaffold from '@/layout/PageScaffold'
import type {
  QrLoginClientOption,
  QrLoginClientsResponse,
  QrLoginRecord,
  QrLoginRecordsResponse,
  QrLoginSession,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

const { Text } = Typography

const STATUS_LABEL: Record<number, string> = {
  0: '等待扫码',
  1: '已扫码，待确认',
  2: '已登录',
  [-1]: '二维码过期',
  [-2]: '已取消',
  [-3]: '结果错误',
}

const STATUS_COLOR: Record<number, string> = {
  0: 'default',
  1: 'gold',
  2: 'green',
  [-1]: 'red',
  [-2]: 'orange',
  [-3]: 'red',
}

export default function QrLoginPage() {
  const [clients, setClients] = useState<QrLoginClientOption[]>([])
  const [records, setRecords] = useState<QrLoginRecord[]>([])
  const [selectedApp, setSelectedApp] = useState<string>()
  const [fileName, setFileName] = useState('cookie')
  const [session, setSession] = useState<QrLoginSession | null>(null)
  const [loadingClients, setLoadingClients] = useState(false)
  const [loadingRecords, setLoadingRecords] = useState(false)
  const [creatingSession, setCreatingSession] = useState(false)

  const loadClients = async () => {
    setLoadingClients(true)
    try {
      const response = await api.get<QrLoginClientsResponse>('/tools/qr-login/clients')
      const items = response.clients ?? []
      setClients(items)
      setSelectedApp((current) => current ?? items[0]?.app)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoadingClients(false)
    }
  }

  const loadRecords = async () => {
    setLoadingRecords(true)
    try {
      const response = await api.get<QrLoginRecordsResponse>('/tools/qr-login/records')
      setRecords(response.records ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoadingRecords(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadClients()
      void loadRecords()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [])

  const isTerminal = useMemo(() => {
    if (!session) {
      return false
    }
    return session.status < 0 || (session.status === 2 && !!session.saved_path)
  }, [session])

  const isPolling = !!session && !isTerminal

  useEffect(() => {
    if (!isPolling || !session) {
      return
    }

    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const next = await api.get<QrLoginSession>(`/tools/qr-login/sessions/${session.session_id}`)
          setSession(next)
          if (next.status === 2 && next.saved_path) {
            void loadRecords()
          }
        } catch (error: unknown) {
          message.error((error as Error).message)
        }
      })()
    }, 2000)

    return () => {
      window.clearInterval(timer)
    }
  }, [isPolling, session])

  const createSession = async () => {
    if (!selectedApp) {
      message.warning('请先选择目标客户端')
      return
    }

    setCreatingSession(true)
    try {
      const response = await api.post<QrLoginSession>('/tools/qr-login/sessions', {
        app: selectedApp,
        file_name: fileName.trim() || 'cookie',
      })
      setSession(response)
      message.success('二维码已生成')
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setCreatingSession(false)
    }
  }

  return (
    <PageScaffold
      title="扫码登录"
      titleLevel={4}
      description="在 React 前端里直接发起 115 Cookie 扫码登录，生成二维码并轮询扫码结果。"
    >
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card className="soft-card" title="创建扫码会话">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Select
                placeholder="目标客户端"
                value={selectedApp}
                options={clients.map((item) => ({ value: item.app, label: `${item.label} (${item.app})` }))}
                loading={loadingClients}
                onChange={setSelectedApp}
              />
              <Input
                value={fileName}
                onChange={(event) => setFileName(event.target.value)}
                placeholder="保存文件名"
              />
              <Space wrap>
                <Button icon={<ReloadOutlined />} onClick={() => void loadClients()} loading={loadingClients}>
                  刷新客户端
                </Button>
                <Button type="primary" icon={<QrcodeOutlined />} onClick={() => void createSession()} loading={creatingSession}>
                  生成二维码
                </Button>
              </Space>
              <Alert
                type="info"
                showIcon
                message="说明"
                description="当前生成的是 Cookie 扫码登录，不会直接回写 Open API token。"
              />
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card className="soft-card" title="二维码与扫码状态">
            {!session && (
              <Alert type="info" showIcon message="请先生成二维码。" />
            )}
            {session && (
              <div className="qr-session-layout">
                <div className="qr-panel">
                  <img className="qr-image" src={session.qr_image_url} alt="115 QR code" />
                </div>
                <div className="qr-meta">
                  <div className="meta-tags">
                    <Tag color={STATUS_COLOR[session.status] ?? 'default'}>
                      {STATUS_LABEL[session.status] ?? session.message}
                    </Tag>
                    <Tag>{session.app}</Tag>
                    <Tag>{isPolling ? '轮询中' : '已停止'}</Tag>
                  </div>
                  <div className="ellipsis-stack">
                    <div>{`UID: ${session.uid}`}</div>
                    <div>{`会话: ${session.session_id}`}</div>
                    <div>{`创建时间: ${formatDateTime(session.created_at)}`}</div>
                    <div>{`更新时间: ${formatDateTime(session.updated_at)}`}</div>
                    {session.saved_path && <div>{`保存路径: ${session.saved_path}`}</div>}
                    {session.error && <div>{`错误: ${session.error}`}</div>}
                  </div>
                  {session.cookies && (
                    <Alert
                      type="success"
                      showIcon
                      message="Cookie 已获取"
                      description={`预览：${session.cookies.slice(0, 200)}`}
                    />
                  )}
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        className="soft-card"
        title="历史记录"
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => void loadRecords()} loading={loadingRecords}>
            刷新
          </Button>
        }
      >
        {!records.length && <Text type="secondary">暂无扫码记录。</Text>}
        <div className="card-stack">
          {records.map((record) => (
            <Card key={`${record.uid}-${record.updated_at}`} size="small">
              <Text strong>{record.file_name}</Text>
              <div className="meta-tags">
                <Tag>{record.app}</Tag>
                <Tag>{record.uid}</Tag>
              </div>
              <div className="ellipsis-stack">
                <div>{record.saved_path || '未保存路径'}</div>
                <div>{formatDateTime(record.updated_at)}</div>
              </div>
            </Card>
          ))}
        </div>
      </Card>
    </PageScaffold>
  )
}
