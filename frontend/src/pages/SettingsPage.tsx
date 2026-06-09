import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Space, Spin, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import type { CookieStatusItem, SystemStatusResponse } from '@/api/types'
import PageScaffold from '@/layout/PageScaffold'
import { formatDateTime } from '@/utils/format'

const { Text } = Typography

const TOKEN_STATUS_META: Record<string, { color: string; label: string }> = {
  ok: { color: 'green', label: '可用' },
  error: { color: 'red', label: '异常' },
  cooldown: { color: 'gold', label: '冷却中' },
  reauth_required: { color: 'orange', label: '需要重新扫码授权' },
  missing: { color: 'default', label: '未配置' },
}

export default function SettingsPage() {
  const [status, setStatus] = useState<SystemStatusResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setErr(null)
    try {
      const data = await api.get<SystemStatusResponse>('/system-status')
      setStatus(data)
    } catch (e: unknown) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  const cookieColumns: ColumnsType<CookieStatusItem> = [
    {
      title: '客户端',
      dataIndex: 'app_description',
      render: (val: string, rec) => (
        <div>
          <div>{val}</div>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>{rec.app}</Text>
          </div>
        </div>
      ),
    },
    {
      title: '文件',
      dataIndex: 'file_name',
      render: (val: string, rec) => (
        <div>
          <div>{val}</div>
          <div>
            <Text type="secondary" style={{ fontSize: 12 }}>{rec.saved_path}</Text>
          </div>
        </div>
      ),
    },
    {
      title: 'UID',
      dataIndex: 'uid',
      width: 120,
    },
    {
      title: '用户名',
      dataIndex: 'user_name',
      width: 120,
      render: (val: string | null) => val ?? '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (val: string, rec) => (
        <div>
          <Tag color={val === 'ok' ? 'green' : 'red'}>{val === 'ok' ? '可用' : '失效'}</Tag>
          {rec.error && (
            <div style={{ marginTop: 4 }}>
              <Text type="danger" style={{ fontSize: 12 }}>{rec.error}</Text>
            </div>
          )}
        </div>
      ),
    },
  ]

  return (
    <PageScaffold
      title="系统状态"
      titleLevel={4}
      actions={<Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新检查</Button>}
    >
      {err && <Alert type="error" message={err} style={{ marginBottom: 16 }} />}

      {loading && <Spin style={{ display: 'block', margin: '32px auto' }} />}

      {!loading && status && (
        <>
          <Card className="soft-card" title="Open API Token" style={{ marginBottom: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="状态">
                <Tag color={TOKEN_STATUS_META[status.token_status]?.color ?? 'red'}>
                  {TOKEN_STATUS_META[status.token_status]?.label ?? status.token_status}
                </Tag>
              </Descriptions.Item>
              {status.token_expires_at && (
                <Descriptions.Item label="Token 到期时间">
                  <span style={{ fontSize: 12 }}>{formatDateTime(status.token_expires_at)}</span>
                </Descriptions.Item>
              )}
              {status.token_error && (
                <Descriptions.Item label="错误">
                  <Text type="danger" style={{ fontSize: 12 }}>{status.token_error}</Text>
                </Descriptions.Item>
              )}
              {status.token_error_at && (
                <Descriptions.Item label="错误时间">
                  <span style={{ fontSize: 12 }}>{formatDateTime(status.token_error_at)}</span>
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card className="soft-card" title={`Cookies（${status.cookies.length} 条记录）`} style={{ marginBottom: 16 }}>
            {status.cookies.length === 0 ? (
              <Text type="secondary">暂无 QR 登录记录。请先到「QR 扫码授权」页面登录。</Text>
            ) : (
              <Table
                rowKey="saved_path"
                dataSource={status.cookies}
                columns={cookieColumns}
                pagination={false}
                size="small"
              />
            )}
          </Card>
        </>
      )}

      <Card className="soft-card" title="快捷链接">
        <Space direction="vertical">
          <a href="/api/docs" target="_blank" rel="noreferrer">API 文档 (Swagger)</a>
          <a href="/auth-center">授权中心</a>
        </Space>
      </Card>
    </PageScaffold>
  )
}
