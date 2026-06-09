import { Statistic } from 'antd'
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
        <Statistic key={item.key} title={item.label} value={item.value} />
      ))}
    </div>
  )
}
