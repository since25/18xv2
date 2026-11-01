export type DateTimeInput = string | number | Date | null | undefined

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes <= 0) {
    return '-'
  }

  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }

  return `${value.toFixed(1).replace(/\.0$/, '')} ${units[unitIndex]}`
}

export function formatDateTime(value: DateTimeInput): string {
  if (!value) {
    return '-'
  }

  const parsed = parseDateTimeInput(value)
  if (Number.isNaN(parsed.getTime())) {
    return typeof value === 'string' ? value.replace('T', ' ').slice(0, 19) : '-'
  }

  return formatShanghaiDateTime(parsed)
}

export function formatShortDateTime(value: DateTimeInput, now = new Date()): string {
  const parsed = parseDateTimeInput(value)
  if (Number.isNaN(parsed.getTime())) {
    return '-'
  }

  const dateParts = getShanghaiParts(parsed)
  const nowYear = getShanghaiParts(now).year
  if (dateParts.year === nowYear) {
    return `${dateParts.month}-${dateParts.day} ${dateParts.hour}:${dateParts.minute}`
  }
  return `${dateParts.year}-${dateParts.month}-${dateParts.day}`
}

export function formatRelative(value: DateTimeInput, now = new Date()): string {
  const parsed = parseDateTimeInput(value)
  if (Number.isNaN(parsed.getTime())) {
    return '-'
  }

  const seconds = Math.max(0, Math.floor((now.getTime() - parsed.getTime()) / 1000))
  if (seconds < 60) return '刚刚'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return '-'
  }

  const totalSeconds = Math.floor(seconds)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const remainingSeconds = totalSeconds % 60
  if (hours > 0) return `${hours} 小时${minutes ? ` ${minutes} 分` : ''}`
  if (minutes > 0) return `${minutes} 分${remainingSeconds ? ` ${remainingSeconds} 秒` : ''}`
  return `${remainingSeconds} 秒`
}

export function splitTextareaLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function normalizeDateTimeInput(value: string): string {
  const trimmed = value.trim()

  // SQLite 常见返回形如 "2026-04-20 14:05:38"，这里按 UTC 存储解释，
  // 再统一格式化到上海时间，避免前端直接显示成 UTC。
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(trimmed)) {
    return trimmed.replace(' ', 'T') + 'Z'
  }

  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(trimmed)) {
    return trimmed + 'Z'
  }

  return trimmed
}

function parseDateTimeInput(value: DateTimeInput): Date {
  if (value instanceof Date) return value
  if (typeof value === 'number') return new Date(value * 1000)
  if (typeof value === 'string') return new Date(normalizeDateTimeInput(value))
  return new Date(Number.NaN)
}

function getShanghaiParts(value: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(value)
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? ''
  return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour'), minute: get('minute'), second: get('second') }
}

function formatShanghaiDateTime(value: Date): string {
  const parts = getShanghaiParts(value)
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}
