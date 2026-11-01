import { formatBytes } from '@/utils/format'

export default function BytesText({ value }: { value: number | null | undefined }) {
  return <span className="numeric-text">{formatBytes(value)}</span>
}
