import { Typography } from 'antd'
import type { ReactNode } from 'react'
import MetricStrip, { type MetricItem } from './MetricStrip'

type PageScaffoldProps = {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  stats?: MetricItem[]
  children: ReactNode
}

export default function PageScaffold({ title, description, actions, stats = [], children }: PageScaffoldProps) {
  return (
    <div className="page-shell">
      <div className="page-header">
        <div className="page-header-copy">
          <Typography.Title level={3} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          {description ? (
            <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
              {description}
            </Typography.Paragraph>
          ) : null}
        </div>
        <div className="page-header-actions">
          {stats.length ? <MetricStrip items={stats} /> : null}
          {actions}
        </div>
      </div>
      {children}
    </div>
  )
}
