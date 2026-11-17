import { PauseCircleOutlined, SyncOutlined } from '@ant-design/icons'
import { Button, Space, Typography, message } from 'antd'
import { controlDownloader, syncDownloaderPackages, syncDownloaderTasks, type DownloaderStatus } from '@/api/downloader'
import { formatRelative } from '@/utils/format'
import { useApiAction } from '@/hooks/useApiAction'

type DownloaderHeaderProps = {
  status: DownloaderStatus | null
  onSynced: () => void
}

// 401 由全局登录过期处理负责提示，这里不重复弹
function showError(messageApi: ReturnType<typeof message.useMessage>[0], error: Error) {
  if ((error as { status?: number }).status === 401) return
  messageApi.error(error.message)
}

export default function DownloaderHeader({ status, onSynced }: DownloaderHeaderProps) {
  const [messageApi, contextHolder] = message.useMessage()
  // 提示统一走本组件的 messageApi，所以两个操作都设为 silent，出错文字在这里自行弹出
  const syncAction = useApiAction(async () => {
    await syncDownloaderPackages()
    await syncDownloaderTasks()
  }, { silent: true })
  const controlAction = useApiAction((state: 'pause' | 'resume') => controlDownloader(state), { silent: true })
  const loading = syncAction.loading

  async function sync() {
    const result = await syncAction.run()
    if (!result.ok) {
      showError(messageApi, result.error)
      return
    }
    messageApi.success('资源包和任务已同步')
    onSynced()
  }

  async function changeState(state: 'pause' | 'resume') {
    const result = await controlAction.run(state)
    if (!result.ok) {
      showError(messageApi, result.error)
      return
    }
    messageApi.success(state === 'pause' ? '已暂停全部下载' : '已恢复全部下载')
    onSynced()
  }

  const ready = Boolean(status?.enabled && status.remote_ready)
  const syncTime = status?.latest_sync?.finished_at ?? status?.latest_sync?.started_at
  return (
    <>
      {contextHolder}
      <Space className="downloader-header" wrap>
        <span className={`downloader-connection-dot ${ready ? 'is-ready' : 'is-offline'}`} aria-hidden="true" />
        <Typography.Text>{ready ? 'RN 已连接' : 'RN 未连接'}</Typography.Text>
        <Typography.Text type="secondary">
          {syncTime ? `上次同步 ${formatRelative(syncTime)}` : '尚未同步'}
        </Typography.Text>
        <Button size="small" icon={<PauseCircleOutlined />} disabled={!ready} onClick={() => void changeState('pause')}>
          暂停全部
        </Button>
        <Button size="small" disabled={!ready} onClick={() => void changeState('resume')}>
          恢复全部
        </Button>
        <Button type="primary" icon={<SyncOutlined />} loading={loading} disabled={!status?.enabled} onClick={() => void sync()}>
          同步资源包
        </Button>
      </Space>
    </>
  )
}
