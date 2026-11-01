import { useCallback, useEffect, useRef, useState } from 'react'
import { message } from 'antd'

export type UndoableIgnoreItem = { packageId: number; title: string }

type UseUndoableIgnoreOptions = {
  commit: (packageIds: number[]) => Promise<void>
  delayMs?: number
}

export function useUndoableIgnore({ commit, delayMs = 5000 }: UseUndoableIgnoreOptions) {
  const [pendingIds, setPendingIds] = useState<Set<number>>(() => new Set())
  const pendingRef = useRef<Set<number>>(new Set())
  const timerRef = useRef<number | null>(null)
  const mountedRef = useRef(true)
  const flushRef = useRef<() => Promise<void>>(async () => undefined)

  const commitBatch = useCallback(async (ids: number[]) => {
    if (!ids.length) return
    try {
      await commit(ids)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '忽略资源包失败')
    } finally {
      if (mountedRef.current) {
        setPendingIds((current) => {
          const next = new Set(current)
          ids.forEach((id) => next.delete(id))
          return next
        })
      }
    }
  }, [commit])

  const flush = useCallback(async () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    const ids = [...pendingRef.current]
    pendingRef.current.clear()
    if (mountedRef.current) setPendingIds(new Set())
    await commitBatch(ids)
  }, [commitBatch])

  useEffect(() => {
    flushRef.current = flush
  }, [flush])

  const schedule = useCallback((items: UndoableIgnoreItem[]) => {
    const ids = [...new Set(items.map((item) => item.packageId))]
    if (!ids.length) return
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
      const previous = [...pendingRef.current]
      pendingRef.current.clear()
      void commitBatch(previous)
    }
    ids.forEach((id) => pendingRef.current.add(id))
    setPendingIds(new Set(pendingRef.current))
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      void flush()
    }, delayMs)
  }, [commitBatch, delayMs, flush])

  const undo = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    pendingRef.current.clear()
    setPendingIds(new Set())
  }, [])

  useEffect(() => {
    mountedRef.current = true
    const handlePageHide = () => {
      void flushRef.current()
    }
    window.addEventListener('pagehide', handlePageHide)
    return () => {
      mountedRef.current = false
      window.removeEventListener('pagehide', handlePageHide)
      void flushRef.current()
    }
  }, [])

  return { schedule, undo, pendingIds, flush }
}
