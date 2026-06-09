import { Card, type CardProps } from 'antd'

function joinClassNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(' ')
}

export default function SurfacePanel({ className, ...props }: CardProps) {
  return <Card {...props} className={joinClassNames('surface-panel', className)} />
}
