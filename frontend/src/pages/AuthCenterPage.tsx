import { Alert, Button, Card, Descriptions, Space, Typography } from 'antd'
import { LinkOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import type { SystemStatusResponse } from '@/api/types'
import PageScaffold from '@/layout/PageScaffold'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { formatDateTime } from '@/utils/format'

const { Paragraph, Text } = Typography

export default function AuthCenterPage() {
  const [status, setStatus] = useState<SystemStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.get<SystemStatusResponse>('/system-status')
        .then(setStatus)
        .catch((err: Error) => setError(err.message))
    }, 0)

    return () => window.clearTimeout(timer)
  }, [])

  return (
    <PageScaffold
      title="授权中心"
      titleLevel={4}
      description="把 Open API Token 授权和 Cookie 扫码入口放到一个地方，避免后续测试时在多个页面来回找。"
    >
      {error && <Alert type="error" showIcon message={error} />}

      <Card className="soft-card">
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="服务状态">
            ok
          </Descriptions.Item>
          <Descriptions.Item label="授权模式">
            open_api_token
          </Descriptions.Item>
          <Descriptions.Item label="OpenAPI Token 状态">
            {status?.token_status ?? '未知'}
          </Descriptions.Item>
          <Descriptions.Item label="最近错误">
            {status?.token_error || '无'}
          </Descriptions.Item>
          <Descriptions.Item label="错误时间">
            {status?.token_error_at ? formatDateTime(status.token_error_at) : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Token 到期">
            {status?.token_expires_at ? formatDateTime(status.token_expires_at) : '未记录'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Space direction="vertical" style={{ width: '100%', marginTop: 16 }} size={16}>
        <Card
          className="soft-card"
          title={<Space><SafetyCertificateOutlined /><span>Open API 扫码授权</span></Space>}
        >
          <Paragraph>
            主系统走的是 <Text code>access token / refresh token</Text> 模式。现在推荐直接使用扫码授权来初始化或重新授权 Open API token。
          </Paragraph>
          <Link to="/auth-center/open-api-qr">
            <Button type="primary">打开 Open API 扫码授权</Button>
          </Link>
        </Card>

        <Card
          className="soft-card"
          title={<Space><SafetyCertificateOutlined /><span>Cookie 扫码登录</span></Space>}
        >
          <Paragraph>
            这条链路当前保存的是 Cookie 文件，主要服务于目录导出等 Cookie 场景，不会直接回写 Open API token。
          </Paragraph>
          <Space wrap>
            <Link to="/auth-center/qr-login">
              <Button type="primary">在前端中打开扫码登录</Button>
            </Link>
            <a href="/api/tools/qr-login" target="_blank" rel="noreferrer">
              <Button icon={<LinkOutlined />}>打开旧版扫码页</Button>
            </a>
          </Space>
        </Card>

        <Alert
          type="info"
          showIcon
          message="当前约定"
          description="Cookie 扫码和 Open API 扫码是两条独立链路。主系统的 Open API token 失效后，优先重新走 Open API 扫码授权。"
        />
      </Space>
    </PageScaffold>
  )
}
