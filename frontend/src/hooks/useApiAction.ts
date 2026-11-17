import { useCallback, useEffect, useRef, useState } from 'react'
import { message } from 'antd'

/** 操作类请求的通用 hook：统一成功提示、出错提示和执行中状态，run 永不抛异常 */
export type ApiActionResult<R> = { ok: true; data: R } | { ok: false; error: Error }

export interface UseApiActionOptions<A extends unknown[], R> {
  successMessage?: string | ((data: R, ...args: A) => string)
  onSuccess?: (data: R, ...args: A) => void | Promise<void>
  silent?: boolean
}

export function useApiAction<A extends unknown[], R>(
  fn: (...args: A) => Promise<R>,
  options: UseApiActionOptions<A, R> = {},
): { run: (...args: A) => Promise<ApiActionResult<R>>; loading: boolean } {
  // 同时进行中的次数；大于 0 即为执行中
  const [pending, setPending] = useState(0)

  // 最新的执行函数和选项放进 ref，run 保持稳定引用
  const fnRef = useRef(fn)
  const optionsRef = useRef(options)
  useEffect(() => {
    fnRef.current = fn
    optionsRef.current = options
  })

  const mountedRef = useRef(false)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const run = useCallback(async (...args: A): Promise<ApiActionResult<R>> => {
    setPending((count) => count + 1)
    try {
      const data = await fnRef.current(...args)
      const { successMessage, onSuccess } = optionsRef.current
      if (successMessage) {
        message.success(typeof successMessage === 'function' ? successMessage(data, ...args) : successMessage)
      }
      if (onSuccess) {
        await onSuccess(data, ...args)
      }
      return { ok: true, data }
    } catch (caught) {
      const error = caught instanceof Error ? caught : new Error(String(caught))
      // 401 由全局登录过期处理负责提示，这里不重复弹
      if (!optionsRef.current.silent && (caught as { status?: number } | null)?.status !== 401) {
        message.error(error.message)
      }
      return { ok: false, error }
    } finally {
      if (mountedRef.current) {
        setPending((count) => count - 1)
      }
    }
  }, [])

  return { run, loading: pending > 0 }
}
