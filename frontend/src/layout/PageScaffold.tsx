import { Typography } from 'antd'
import type { ReactNode } from 'react'
import MetricStrip, { type MetricItem } from './MetricStrip'

type PageScaffoldProps = {
  className?: string
  title: ReactNode
  titleLevel?: 1 | 2 | 3 | 4 | 5
  description?: ReactNode
  actions?: ReactNode
  stats?: MetricItem[]
  children: ReactNode
}

function joinClassNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(' ')
}

export default function PageScaffold({
  className,
  title,
  titleLevel = 3,
  description,
  actions,
  stats = [],
  children,
}: PageScaffoldProps) {
  return (
    <div className={joinClassNames('page-shell', className)}>
      <header className="page-header">
        <div className="page-header-copy">
          <Typography.Title level={titleLevel} style={{ margin: 0 }}>
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
      </header>
      {children}
    </div>
  )
}
