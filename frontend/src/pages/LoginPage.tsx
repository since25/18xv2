import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'

type LoginPageProps = {
  defaultUsername: string
  loading: boolean
  error: string | null
  onSubmit: (values: { username: string; password: string }) => Promise<void>
}

export default function LoginPage({ defaultUsername, loading, error, onSubmit }: LoginPageProps) {
  return (
    <div className="login-shell">
      <div className="login-hero">
        <Typography.Text className="login-eyebrow">18x Organizer</Typography.Text>
        <Typography.Title level={1} className="login-title">
          域名访问先登录，再进入管理台
        </Typography.Title>
        <Typography.Paragraph className="login-description">
          这里的登录用于保护 115 授权信息、执行接口和管理页面。首次 Docker 启动生成的密码只会在容器日志中出现一次。
        </Typography.Paragraph>
      </div>

      <Card className="soft-card login-card" bordered={false}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          管理员登录
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          用户名来自 `.env`，密码来自容器首次启动日志。
        </Typography.Paragraph>
        {error ? <Alert showIcon type="error" message={error} style={{ marginBottom: 16 }} /> : null}
        <Form
          layout="vertical"
          initialValues={{ username: defaultUsername, password: '' }}
          onFinish={onSubmit}
          autoComplete="off"
        >
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="管理员用户名" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="请输入初始密码或当前密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            登录进入系统
          </Button>
        </Form>
      </Card>
    </div>
  )
}
