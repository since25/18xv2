import type { ReactNode } from 'react'

export type MetricItem = {
  key: string
  label: ReactNode
  value: string | number
}

export default function MetricStrip({ items }: { items: MetricItem[] }) {
  if (!items.length) {
    return null
  }

  return (
    <div className="metric-strip">
      {items.map((item) => (
        <div className="metric-item" key={item.key}>
          <span className="metric-label">{item.label}</span>
          <strong className="metric-value">{item.value}</strong>
        </div>
      ))}
    </div>
  )
}
