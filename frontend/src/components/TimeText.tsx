import { Tooltip } from 'antd'
import { formatDateTime, formatRelative, type DateTimeInput } from '@/utils/format'

export default function TimeText({ value, relative = false }: { value: DateTimeInput; relative?: boolean }) {
  const full = formatDateTime(value)
  const display = relative ? formatRelative(value) : full
  return <Tooltip title={full}><span className="numeric-text">{display}</span></Tooltip>
}
