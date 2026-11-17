import { useCallback, useEffect, useRef, useState } from 'react'
import type { DependencyList } from 'react'
import { message } from 'antd'

/** 读取类请求的通用 hook：自动加载、依赖变化重取、只采用最后一次请求的结果 */
export interface UseApiQueryOptions<T> {
  enabled?: boolean      // 默认 true；false 时不自动执行
  silent?: boolean       // 默认 false；true 时出错不弹提示
  initialData?: T
}

export interface UseApiQueryResult<T> {
  data: T | undefined    // 传了 initialData 时类型为 T
  loading: boolean
  error: Error | null
  reload: (options?: { silent?: boolean }) => Promise<void>  // silent: 不切换 loading
  setData: (updater: T | ((prev: T | undefined) => T)) => void
}

// 逐项比较依赖（与 React 比较依赖的方式一致）
function sameDeps(a: DependencyList, b: DependencyList) {
  return a.length === b.length && a.every((item, index) => Object.is(item, b[index]))
}

export function useApiQuery<T>(
  fetcher: () => Promise<T>,
  deps: DependencyList,
  options: UseApiQueryOptions<T> & { initialData: T },
): UseApiQueryResult<T> & { data: T }
export function useApiQuery<T>(
  fetcher: () => Promise<T>,
  deps: DependencyList,
  options?: UseApiQueryOptions<T>,
): UseApiQueryResult<T>
export function useApiQuery<T>(
  fetcher: () => Promise<T>,
  deps: DependencyList,
  options: UseApiQueryOptions<T> = {},
): UseApiQueryResult<T> {
  const { enabled = true, silent = false, initialData } = options
  const [data, setDataState] = useState<T | undefined>(initialData)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(enabled)

  // 依赖（含 enabled）变化时，在渲染阶段同步把 loading 置真；
  // 这是 React 文档推荐的“渲染中按前值调整状态”写法，避免在 effect 里同步 setState
  const key = [enabled, ...deps]
  const [trackedKey, setTrackedKey] = useState<DependencyList>(key)
  if (!sameDeps(trackedKey, key)) {
    setTrackedKey(key)
    setLoading(enabled)
  }

  // 最新的取数函数和提示开关放进 ref，避免它们每次渲染变化导致重复请求
  const fetcherRef = useRef(fetcher)
  const silentRef = useRef(silent)
  useEffect(() => {
    fetcherRef.current = fetcher
    silentRef.current = silent
  })

  const seqRef = useRef(0)
  const mountedRef = useRef(false)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // 发出一次请求；只有最后一次发出的请求、且组件仍挂载时才更新状态
  const execute = useCallback(async () => {
    const seq = ++seqRef.current
    const isLatest = () => mountedRef.current && seq === seqRef.current
    try {
      const result = await fetcherRef.current()
      if (isLatest()) {
        setDataState(() => result)
        setError(null)
      }
    } catch (caught) {
      if (isLatest()) {
        const err = caught instanceof Error ? caught : new Error(String(caught))
        setError(err)
        // 401 由全局登录过期处理负责提示，这里不重复弹
        if (!silentRef.current && (caught as { status?: number } | null)?.status !== 401) {
          message.error(err.message)
        }
      }
    } finally {
      if (isLatest()) {
        setLoading(false)
      }
    }
  }, [])

  // 挂载和依赖变化时自动执行
  useEffect(() => {
    if (!trackedKey[0]) return
    void execute()
  }, [trackedKey, execute])

  const reload = useCallback(async (reloadOptions?: { silent?: boolean }) => {
    if (!reloadOptions?.silent) {
      setLoading(true)
    }
    await execute()
  }, [execute])

  const setData = useCallback((updater: T | ((prev: T | undefined) => T)) => {
    setDataState((prev) => (
      typeof updater === 'function' ? (updater as (prev: T | undefined) => T)(prev) : updater
    ))
  }, [])

  return { data, loading, error, reload, setData }
}
