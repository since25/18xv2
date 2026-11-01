import type { ReactNode } from 'react'

type DataToolbarProps = {
  left?: ReactNode
  right?: ReactNode
  children?: ReactNode
}

export default function DataToolbar({ left, right, children }: DataToolbarProps) {
  return (
    <div className="data-toolbar">
      {left ? <div className="data-toolbar-left">{left}</div> : null}
      {children}
      {right ? <div className="data-toolbar-right">{right}</div> : null}
    </div>
  )
}
