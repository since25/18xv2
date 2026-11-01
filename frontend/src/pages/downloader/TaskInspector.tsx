import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Collapse, Drawer, Input, Segmented, Space, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { getTaskDetail, retryDownloaderTask, type TaskDetail, type TaskFile } from '@/api/downloader'
import BytesText from '@/components/BytesText'
import StatusTag from '@/components/StatusTag'
import { formatDuration } from '@/utils/format'

type TaskInspectorProps = {
  taskId: string | null
  onClose: () => void
  onChanged: () => void
}

type FileFilter = 'all' | 'failed' | 'success'

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

export default function TaskInspector({ taskId, onClose, onChanged }: TaskInspectorProps) {
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [filename, setFilename] = useState('')
  const [fileFilter, setFileFilter] = useState<FileFilter>('all')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!taskId) {
      const timer = window.setTimeout(() => setDetail(null), 0)
      return () => window.clearTimeout(timer)
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      if (cancelled) return
      setLoading(true)
      void getTaskDetail(taskId).then((payload) => {
        if (!cancelled) setDetail(payload)
      }).catch((error) => message.error(errorText(error))).finally(() => {
        if (!cancelled) setLoading(false)
      })
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [taskId])

  const files = useMemo(() => {
    const source = detail?.files ?? []
    const query = filename.trim().toLocaleLowerCase()
    return source.filter((file) => {
      if (fileFilter === 'failed' && !['failed', 'download_failed', 'upload_failed'].includes(file.status ?? '')) return false
      if (fileFilter === 'success' && !['completed', 'downloaded'].includes(file.status ?? '')) return false
      return !query || (file.filename ?? '').toLocaleLowerCase().includes(query)
    })
  }, [detail?.files, fileFilter, filename])

  async function retryFailed() {
    if (!taskId) return
    try {
      await retryDownloaderTask(taskId, { onlyFailed: true })
      onChanged()
    } catch (error) {
      message.error(errorText(error))
    }
  }

  const columns: ColumnsType<TaskFile> = [
    { title: '文件名', dataIndex: 'filename', key: 'filename', render: (value) => value || '-' },
    { title: '大小', dataIndex: 'total_size', key: 'total_size', render: (value) => <BytesText value={value} /> },
    { title: '状态', dataIndex: 'status', key: 'status', render: (value) => <StatusTag domain="file" value={value} /> },
    { title: '错误原因', dataIndex: 'error', key: 'error', render: (value) => value || '-' },
  ]

  const failedFiles = detail?.failed_files ?? []
  return (
    <Drawer
      title={detail?.task.title || (taskId ? `任务详情：${taskId}` : '任务详情')}
      size={560}
      open={Boolean(taskId)}
      keyboard
      maskClosable
      onClose={onClose}
      loading={loading}
    >
      {detail ? <div className="task-inspector">
        <div className="task-inspector-summary">
          <StatusTag domain="task" value={detail.task.status} />
          <span>耗时：{formatDuration(detail.task.duration_seconds)}</span>
          <span className="numeric-text">已下 / 总量：<BytesText value={detail.task.downloaded_bytes} /> / <BytesText value={detail.task.total_bytes} /></span>
          <span>{detail.task.package_title || detail.task.title || '-'} · {detail.task.channel_title || '未标注频道'}</span>
        </div>
        {failedFiles.length ? <Alert
          type="warning"
          showIcon
          title={`${failedFiles.length} 个文件下载异常`}
          action={<Button type="primary" size="small" onClick={() => void retryFailed()}>重试全部失败文件</Button>}
          description={<div className="task-failed-files">{failedFiles.map((file) => <div className="task-failed-file" key={file.message_id}><strong>{file.filename || '-'}</strong><BytesText value={file.total_size} /><span>{file.error || '未知错误'}</span></div>)}</div>}
        /> : null}
        <div className="task-inspector-files">
          <Space className="task-inspector-file-toolbar" wrap>
            <Typography.Text strong>文件清单（共 {detail.files.length} 个）</Typography.Text>
            <Input placeholder="搜索文件名" value={filename} onChange={(event) => setFilename(event.target.value)} allowClear />
            <Segmented value={fileFilter} onChange={(value) => setFileFilter(value as FileFilter)} options={[{ label: '全部', value: 'all' }, { label: '仅失败', value: 'failed' }, { label: '仅成功', value: 'success' }]} />
          </Space>
          <Table<TaskFile> rowKey="message_id" size="small" virtual scroll={{ y: 360 }} pagination={false} columns={columns} dataSource={files} locale={{ emptyText: '没有匹配的文件' }} />
        </div>
        <Collapse items={[{ key: 'history', label: '变更历史', children: detail.history.length ? detail.history.map((entry, index) => <div key={entry.id ?? index}>{String(entry.observed_at ?? '-')} · {String(entry.status ?? '-')}</div>) : '暂无变更历史' }]} />
      </div> : null}
    </Drawer>
  )
}
