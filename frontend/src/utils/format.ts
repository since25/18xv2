export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '-'
  }

  const normalized = normalizeDateTimeInput(value)
  const parsed = new Date(normalized)
  if (Number.isNaN(parsed.getTime())) {
    return value.replace('T', ' ').slice(0, 19)
  }

  const formatter = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })

  return formatter.format(parsed).replace('T', ' ')
}

export function splitTextareaLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function normalizeDateTimeInput(value: string): string {
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
