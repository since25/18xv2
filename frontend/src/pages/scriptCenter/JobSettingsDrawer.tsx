import { useEffect, useState } from 'react'
import { Alert, Button, Divider, Drawer, Form, Input, InputNumber, Radio, Space, Switch, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

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

interface OrganizeJob {
  scan_root: string
  target_root: string
}

interface SettingsForm {
  enabled: boolean
  run_time: string
  executor: string
  pages?: number
  forum_url?: string
  qb_category?: string
  source_dir?: string
  target_dir?: string
  delete_dirs_text?: string
  organize_jobs?: OrganizeJob[]
  merge_on_conflict?: boolean
  fix_permissions?: boolean
}

const MOVE = 'MOVE_SSD_CACHE_TO_DISK2'
const DEL = 'DEL_SOMETHING'

/** 按脚本取出要提交的参数；目录的合法性由后端校验（必须在容器挂载的两个根目录之下） */
function paramsFor(jobName: string, values: SettingsForm): Record<string, unknown> | undefined {
  if (jobName === 'sehuatang') {
    return { pages: Number(values.pages), forum_url: values.forum_url, qb_category: values.qb_category }
  }
  if (jobName === MOVE) {
    return { source_dir: (values.source_dir ?? '').trim(), target_dir: (values.target_dir ?? '').trim() }
  }
  if (jobName === DEL) {
    return {
      delete_dirs: (values.delete_dirs_text ?? '').split('\n').map((line) => line.trim()).filter(Boolean),
      organize_jobs: (values.organize_jobs ?? []).map((item) => ({
        scan_root: (item?.scan_root ?? '').trim(),
        target_root: (item?.target_root ?? '').trim(),
      })),
      merge_on_conflict: Boolean(values.merge_on_conflict),
      fix_permissions: Boolean(values.fix_permissions),
    }
  }
  return undefined
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

/** 脚本设置：开关、运行时间、执行方和参数。判定规则写死在脚本里，不在这里改。 */
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
      source_dir: params.source_dir as string | undefined,
      target_dir: params.target_dir as string | undefined,
      delete_dirs_text: ((params.delete_dirs as string[] | undefined) ?? []).join('\n'),
      organize_jobs: (params.organize_jobs as OrganizeJob[] | undefined) ?? [],
      merge_on_conflict: params.merge_on_conflict as boolean | undefined,
      fix_permissions: params.fix_permissions as boolean | undefined,
    })
  }, [job, form])

  if (!job) return null

  const save = async () => {
    const values = form.getFieldsValue(true) as SettingsForm
    const params = paramsFor(job.job_name, values)
    setSaving(true)
    setError(null)
    try {
      await updateScriptJob(job.job_name, {
        enabled: values.enabled,
        run_time: values.run_time,
        executor: values.executor,
        ...(params ? { params } : {}),
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
        ) : null}
        {job.job_name === MOVE && (
          <>
            <Form.Item label="源目录" name="source_dir">
              <Input />
            </Form.Item>
            <Form.Item label="目标目录" name="target_dir">
              <Input />
            </Form.Item>
          </>
        )}
        {job.job_name === DEL && (
          <>
            <Text type="secondary">判定规则不在这里改；关键词在「关键词」页管理。</Text>
            <Form.Item label="删除扫描目录（每行一个）" name="delete_dirs_text" style={{ marginTop: 12 }}>
              <Input.TextArea rows={4} />
            </Form.Item>
            <Form.Item label="整理任务（扫描目录 → 整理到）">
              <Form.List name="organize_jobs">
                {(fields, { add, remove }) => (
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    {fields.map((field, index) => (
                      <Space key={field.key} align="start" style={{ width: '100%' }}>
                        <Form.Item name={[field.name, 'scan_root']} noStyle>
                          <Input aria-label={`第 ${index + 1} 条扫描目录`} placeholder="扫描目录" style={{ width: 200 }} />
                        </Form.Item>
                        <Form.Item name={[field.name, 'target_root']} noStyle>
                          <Input aria-label={`第 ${index + 1} 条整理到`} placeholder="整理到" style={{ width: 200 }} />
                        </Form.Item>
                        <Button icon={<DeleteOutlined />} aria-label={`删除第 ${index + 1} 条整理任务`}
                          onClick={() => remove(field.name)} />
                      </Space>
                    ))}
                    <Button icon={<PlusOutlined />} onClick={() => add({ scan_root: '', target_root: '' })}>添加一条</Button>
                  </Space>
                )}
              </Form.List>
            </Form.Item>
            <Form.Item label="同名目录合并" name="merge_on_conflict" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label="跑完修正权限" name="fix_permissions" valuePropName="checked">
              <Switch />
            </Form.Item>
          </>
        )}
      </Form>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      <Button type="primary" onClick={save} loading={saving}>保存设置</Button>
      {isSehuatang && <SiteSessionSection job={job} onSaved={onSaved} />}
    </Drawer>
  )
}
