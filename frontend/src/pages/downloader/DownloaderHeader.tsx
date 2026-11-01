import { PauseCircleOutlined, SyncOutlined } from '@ant-design/icons'
import { Button, Space, Typography, message } from 'antd'
import { useState } from 'react'
import { controlDownloader, syncDownloaderPackages, syncDownloaderTasks, type DownloaderStatus } from '@/api/downloader'
import { formatRelative } from '@/utils/format'

type DownloaderHeaderProps = {
  status: DownloaderStatus | null
  onSynced: () => void
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function DownloaderHeader({ status, onSynced }: DownloaderHeaderProps) {
  const [messageApi, contextHolder] = message.useMessage()
  const [loading, setLoading] = useState(false)

  async function sync() {
    setLoading(true)
    try {
      await syncDownloaderPackages()
      await syncDownloaderTasks()
      messageApi.success('资源包和任务已同步')
      onSynced()
    } catch (error) {
      messageApi.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }

  async function changeState(state: 'pause' | 'resume') {
    try {
      await controlDownloader(state)
      messageApi.success(state === 'pause' ? '已暂停全部下载' : '已恢复全部下载')
      onSynced()
    } catch (error) {
      messageApi.error(errorText(error))
    }
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
