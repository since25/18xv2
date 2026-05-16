import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Row, Space, Tag, Typography, message } from 'antd'
import { QrcodeOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import type { OpenAuthRecord, OpenAuthRecordsResponse, OpenAuthSession } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const { Paragraph, Text, Title } = Typography

const STATUS_LABEL: Record<number, string> = {
  0: '等待扫码',
  1: '已扫码，待确认',
  2: '授权完成',
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

export default function OpenAuthPage() {
  const [records, setRecords] = useState<OpenAuthRecord[]>([])
  const [session, setSession] = useState<OpenAuthSession | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)
  const [loadingRecords, setLoadingRecords] = useState(false)

  const loadRecords = async () => {
    setLoadingRecords(true)
    try {
      const response = await api.get<OpenAuthRecordsResponse>('/tools/open-auth/records')
      setRecords(response.records ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoadingRecords(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadRecords()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  const isTerminal = useMemo(() => {
    if (!session) {
      return false
    }
    return session.status < 0 || session.status === 2
  }, [session])

  const isPolling = !!session && !isTerminal

  useEffect(() => {
    if (!isPolling || !session) {
      return
    }

    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const next = await api.get<OpenAuthSession>(`/tools/open-auth/sessions/${session.session_id}`)
          setSession(next)
          if (next.status === 2) {
            void loadRecords()
            void message.success('Open API token 已更新')
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
    setCreatingSession(true)
    try {
      const response = await api.post<OpenAuthSession>('/tools/open-auth/sessions')
      setSession(response)
      message.success('Open API 扫码二维码已生成')
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setCreatingSession(false)
    }
  }

  return (
    <div className="page-shell">
      <div className="page-header">
        <div>
          <Title level={4} style={{ margin: 0 }}>Open API 扫码授权</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            这条链路会直接获取并持久化 115 Open API token，适合作为新环境初始化和失效后重新授权的主入口。
          </Paragraph>
        </div>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card className="soft-card" title="创建授权会话">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Button type="primary" icon={<QrcodeOutlined />} onClick={() => void createSession()} loading={creatingSession}>
                生成授权二维码
              </Button>
              <Alert
                type="info"
                showIcon
                message="说明"
                description="扫码确认后，后端会把新的 access token / refresh token 和有效期写入 data/tokens.json。"
              />
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card className="soft-card" title="二维码与授权状态">
            {!session && <Alert type="info" showIcon message="请先生成二维码。" />}
            {session && (
              <div className="qr-session-layout">
                <div className="qr-panel">
                  <img className="qr-image" src={session.qr_image_url} alt="115 Open API QR code" />
                </div>
                <div className="qr-meta">
                  <div className="meta-tags">
                    <Tag color={STATUS_COLOR[session.status] ?? 'default'}>
                      {STATUS_LABEL[session.status] ?? session.message}
                    </Tag>
                    <Tag>{isPolling ? '轮询中' : '已停止'}</Tag>
                  </div>
                  <div className="ellipsis-stack">
                    <div>{`UID: ${session.uid}`}</div>
                    <div>{`会话: ${session.session_id}`}</div>
                    <div>{`创建时间: ${formatDateTime(session.created_at)}`}</div>
                    <div>{`更新时间: ${formatDateTime(session.updated_at)}`}</div>
                    {session.error && <div>{`错误: ${session.error}`}</div>}
                  </div>
                </div>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        className="soft-card"
        title="最近 Open API 授权记录"
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => void loadRecords()} loading={loadingRecords}>
            刷新
          </Button>
        }
      >
        {!records.length && <Text type="secondary">暂无 Open API 扫码授权记录。</Text>}
        <div className="card-stack">
          {records.map((record, index) => (
            <Card key={`${record.created_at}-${index}`} size="small">
              <Text strong>{formatDateTime(record.created_at)}</Text>
              <div className="ellipsis-stack">
                <div>{`授权时间: ${formatDateTime(record.created_at)}`}</div>
                <div>{`Token 到期: ${record.token_expires_at ? formatDateTime(record.token_expires_at) : '未记录'}`}</div>
              </div>
            </Card>
          ))}
        </div>
      </Card>
    </div>
  )
}
