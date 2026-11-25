import { useEffect, useState } from 'react'
import { Alert, Button, Divider, Drawer, Form, Input, InputNumber, Radio, Space, Switch, Typography } from 'antd'

import { updateScriptJob, updateSiteSession } from '@/api/scriptJobs'
import type { ScriptJob } from '@/api/scriptJobs'
import TimeText from '@/components/TimeText'

const { Text } = Typography

interface JobSettingsDrawerProps {
  job: ScriptJob | null
  open: boolean
  onClose: () => void
  onSaved: () => void
}

interface SettingsForm {
  enabled: boolean
  run_time: string
  executor: string
  pages?: number
  forum_url?: string
  qb_category?: string
}

function errorText(err: unknown) {
  return err instanceof Error ? err.message : String(err)
}

/** 站点 cookie 一节：只显示是否已设置，不回显旧值；保存后清空输入框 */
function SiteSessionSection({ job, onSaved }: { job: ScriptJob; onSaved: () => void }) {
  const [cookie, setCookie] = useState('')
  const [userAgent, setUserAgent] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const status = job.site_session

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await updateSiteSession(cookie, userAgent)
      setCookie('')
      setUserAgent('')
      onSaved()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Divider plain>站点 cookie</Divider>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {status?.configured ? (
          <Text>已设置，最后更新 <TimeText value={status.updated_at ?? ''} /></Text>
        ) : (
          <Text type="warning">未设置</Text>
        )}
        <Text type="secondary">在已登录站点的浏览器里复制整段 Cookie 和该浏览器的 User-Agent，两者要来自同一个浏览器。</Text>
        <label htmlFor="site-cookie">站点 cookie</label>
        <Input.TextArea id="site-cookie" aria-label="站点 cookie" rows={3} value={cookie}
          onChange={(event) => setCookie(event.target.value)} />
        <label htmlFor="site-ua">浏览器 User-Agent</label>
        <Input id="site-ua" aria-label="浏览器 User-Agent" value={userAgent}
          onChange={(event) => setUserAgent(event.target.value)} />
        {error && <Alert type="error" showIcon message={error} />}
        <Button onClick={save} loading={saving} disabled={!cookie.trim() || userAgent.trim().length < 10}>
          保存 cookie
        </Button>
      </Space>
    </>
  )
}

/** 脚本设置：开关、运行时间、执行方和参数。MOVE、DEL 的参数本阶段只读展示。 */
export default function JobSettingsDrawer({ job, open, onClose, onSaved }: JobSettingsDrawerProps) {
  const [form] = Form.useForm<SettingsForm>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isSehuatang = job?.job_name === 'sehuatang'

  // 换一个脚本时由调用方用 key 重新挂载，错误提示随之清空
  useEffect(() => {
    if (!job) return
    const params = job.params as Record<string, unknown>
    form.setFieldsValue({
      enabled: job.enabled,
      run_time: job.run_time,
      executor: job.executor,
      pages: params.pages as number | undefined,
      forum_url: params.forum_url as string | undefined,
      qb_category: params.qb_category as string | undefined,
    })
  }, [job, form])

  if (!job) return null

  const save = async () => {
    const values = form.getFieldsValue(true) as SettingsForm
    setSaving(true)
    setError(null)
    try {
      await updateScriptJob(job.job_name, {
        enabled: values.enabled,
        run_time: values.run_time,
        executor: values.executor,
        ...(isSehuatang
          ? { params: { pages: Number(values.pages), forum_url: values.forum_url, qb_category: values.qb_category } }
          : {}),
      })
      onSaved()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open={open} onClose={onClose} title={`设置：${job.label}`} width={520} destroyOnClose>
      <Form form={form} layout="vertical">
        <Form.Item label="执行方" name="executor"
          extra={job.runnable ? '改成 18x 前，先在 Unraid 上停掉这个脚本的定时' : undefined}>
          <Radio.Group disabled={!job.runnable}>
            <Radio value="unraid">Unraid</Radio>
            <Radio value="18x">18x</Radio>
          </Radio.Group>
        </Form.Item>
        {!job.runnable && <Text type="secondary">尚未支持在 18x 执行</Text>}
        <Form.Item label="定时启用" name="enabled" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item label="每天运行时间（HH:MM）" name="run_time">
          <Input style={{ width: 120 }} />
        </Form.Item>
        {isSehuatang ? (
          <>
            <Form.Item label="抓几页" name="pages" htmlFor="sehuatang-pages">
              <InputNumber id="sehuatang-pages" aria-label="抓几页" min={1} max={20} />
            </Form.Item>
            <Form.Item label="版块地址（{page} 是页码）" name="forum_url">
              <Input />
            </Form.Item>
            <Form.Item label="qB 分类" name="qb_category">
              <Input style={{ width: 200 }} />
            </Form.Item>
          </>
        ) : (
          <Form.Item label="参数（本阶段只读）">
            <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap', margin: 0 }}>{JSON.stringify(job.params, null, 2)}</pre>
          </Form.Item>
        )}
      </Form>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      <Button type="primary" onClick={save} loading={saving}>保存设置</Button>
      {isSehuatang && <SiteSessionSection job={job} onSaved={onSaved} />}
    </Drawer>
  )
}
