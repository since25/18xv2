import { Button, Space } from 'antd'
import { createPortal } from 'react-dom'
import { formatBytes } from '@/utils/format'

type FloatingActionBarProps = {
  count: number
  totalBytes: number
  onSelectAll: () => void
  onClear: () => void
  onIgnore: () => void
  onSubmit: () => void
  loading?: boolean
}

export default function FloatingActionBar({
  count,
  totalBytes,
  onSelectAll,
  onClear,
  onIgnore,
  onSubmit,
  loading = false,
}: FloatingActionBarProps) {
  if (!count) return null
  return createPortal(
    <div className="downloader-floating-bar" role="status">
      <Space wrap>
        <strong>已选 {count} 项</strong>
        <span className="numeric-text">(共 {formatBytes(totalBytes)})</span>
        <Button type="link" size="small" onClick={onSelectAll}>全选当前页</Button>
        <Button type="link" size="small" onClick={onClear}>清空</Button>
      </Space>
      <Space wrap>
        <Button onClick={onIgnore}>忽略所选</Button>
        <Button type="primary" loading={loading} onClick={onSubmit}>确认下载 {count} 个 (Enter)</Button>
      </Space>
    </div>,
    document.body,
  )
}
