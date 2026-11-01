import { Tooltip } from 'antd'
import type { ReactNode } from 'react'
import { statusMeta, type StatusDomain } from '@/utils/statusText'

type StatusTagProps = {
  domain: StatusDomain
  value: string | null | undefined
  suffix?: ReactNode
  tooltip?: ReactNode
}

export default function StatusTag({ domain, value, suffix, tooltip }: StatusTagProps) {
  const meta = statusMeta(domain, value)
  const content = <span className={`status-tag status-tag--${meta.tone}`}>{meta.label}{suffix ? ` (${suffix})` : ''}</span>
  return tooltip ? <Tooltip title={tooltip}>{content}</Tooltip> : content
}
