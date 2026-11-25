import { useEffect, useState } from 'react'
import { Alert, Typography } from 'antd'

import { getScriptRunLog } from '@/api/scriptRuns'

const { Text } = Typography
const POLL_MS = 2000

/** 实时日志：运行中每 2 秒按偏移追加新内容，结束后停止轮询。换一次运行时由调用方用 key 重新挂载。 */
export default function RunLogPanel({ runId }: { runId: number }) {
  const [text, setText] = useState('')
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    let offset = 0

    const load = async () => {
      try {
        const chunk = await getScriptRunLog(runId, offset)
        if (cancelled) return
        offset = chunk.next_offset
        if (chunk.text) setText((prev) => prev + chunk.text)
        if (chunk.finished) {
          setFinished(true)
          return
        }
        // 这次读到了内容说明可能还有积压（单次最多 64KB），马上接着读；没内容再等 2 秒
        timer = setTimeout(load, chunk.text ? 0 : POLL_MS)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }
    void load()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [runId])

  if (error) return <Alert type="error" showIcon message={`日志加载失败：${error}`} />
  return (
    <div>
      {!finished && <Text type="secondary">运行中，日志自动刷新…</Text>}
      <pre
        data-testid="run-log"
        style={{
          maxHeight: 420,
          overflow: 'auto',
          margin: '8px 0 0',
          padding: 12,
          background: 'var(--app-bg-muted)',
          border: '1px solid var(--app-border)',
          borderRadius: 8,
          fontSize: 12,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {text}
      </pre>
    </div>
  )
}
