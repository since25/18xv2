import type { ReactNode } from 'react'

export default function DataToolbar({ children }: { children: ReactNode }) {
  return <div className="data-toolbar">{children}</div>
}
