export type StatusDomain = 'package' | 'task' | 'file' | 'import' | 'keyword' | 'workflow' | 'auth' | 'review'
export type StatusTone = 'neutral' | 'info' | 'active' | 'success' | 'warning' | 'danger'

type StatusMeta = { label: string; tone: StatusTone }

const STATUS_MAP: Record<StatusDomain, Record<string, StatusMeta>> = {
  package: {
    never: { label: '未下载', tone: 'neutral' },
    queued: { label: '排队中', tone: 'info' },
    downloading: { label: '下载中', tone: 'active' },
    completed: { label: '已下载', tone: 'success' },
    outdated: { label: '有更新', tone: 'warning' },
    failed: { label: '下载异常', tone: 'danger' },
    cancelled: { label: '已取消', tone: 'neutral' },
  },
  task: {
    pending: { label: '排队中', tone: 'info' },
    queued: { label: '排队中', tone: 'info' },
    running: { label: '下载中', tone: 'active' },
    downloading: { label: '下载中', tone: 'active' },
    completed: { label: '已完成', tone: 'success' },
    completed_with_errors: { label: '部分完成', tone: 'warning' },
    failed: { label: '失败', tone: 'danger' },
    cancelled: { label: '已取消', tone: 'neutral' },
    paused: { label: '已暂停', tone: 'warning' },
  },
  file: {
    completed: { label: '已完成', tone: 'success' },
    downloaded: { label: '已完成', tone: 'success' },
    failed: { label: '失败', tone: 'danger' },
    download_failed: { label: '失败', tone: 'danger' },
    downloading: { label: '下载中', tone: 'active' },
    pending: { label: '等待中', tone: 'info' },
    upload_failed: { label: '上传失败', tone: 'danger' },
  },
  import: {
    pending: { label: '等待中', tone: 'info' },
    running: { label: '处理中', tone: 'active' },
    done: { label: '已完成', tone: 'success' },
    completed: { label: '已完成', tone: 'success' },
    failed: { label: '失败', tone: 'danger' },
  },
  keyword: {
    active: { label: '启用', tone: 'success' },
    disabled: { label: '停用', tone: 'neutral' },
    new: { label: '新词', tone: 'info' },
    similar: { label: '相似', tone: 'warning' },
    matched: { label: '已匹配', tone: 'success' },
    ignored: { label: '已忽略', tone: 'neutral' },
    existing: { label: '库中已有', tone: 'success' },
    conflict: { label: '冲突', tone: 'danger' },
  },
  workflow: {
    pending: { label: '待处理', tone: 'info' },
    pending_review: { label: '待审核', tone: 'info' },
    queued: { label: '排队中', tone: 'info' },
    running: { label: '执行中', tone: 'active' },
    planned: { label: '已计划', tone: 'info' },
    confirmed: { label: '已确认', tone: 'success' },
    dismissed: { label: '已忽略', tone: 'neutral' },
    completed: { label: '已完成', tone: 'success' },
    failed: { label: '失败', tone: 'danger' },
    blocked: { label: '已阻塞', tone: 'warning' },
    skipped: { label: '已跳过', tone: 'neutral' },
    draft: { label: '草稿', tone: 'neutral' },
    applied: { label: '已应用', tone: 'success' },
    cancelled: { label: '已取消', tone: 'neutral' },
    submitted: { label: '已提交', tone: 'success' },
    duplicate_skipped: { label: '重复跳过', tone: 'warning' },
    clear: { label: '无重复', tone: 'success' },
    duplicate_found: { label: '发现重复', tone: 'danger' },
    task_exists: { label: '任务已存在', tone: 'warning' },
    deleted: { label: '已删除', tone: 'success' },
  },
  auth: {
    '0': { label: '等待扫码', tone: 'neutral' },
    '1': { label: '已扫码，待确认', tone: 'warning' },
    '2': { label: '已完成', tone: 'success' },
    '-1': { label: '二维码过期', tone: 'danger' },
    '-2': { label: '已取消', tone: 'neutral' },
    '-3': { label: '结果错误', tone: 'danger' },
    polling: { label: '轮询中', tone: 'active' },
    stopped: { label: '已停止', tone: 'neutral' },
    ok: { label: '可用', tone: 'success' },
    valid: { label: '有效', tone: 'success' },
    invalid: { label: '失效', tone: 'danger' },
    pending: { label: '处理中', tone: 'info' },
    expired: { label: '已过期', tone: 'warning' },
    created: { label: '已创建', tone: 'info' },
    authorized: { label: '已授权', tone: 'success' },
    error: { label: '异常', tone: 'danger' },
    cooldown: { label: '冷却中', tone: 'warning' },
    reauth_required: { label: '需要重新授权', tone: 'warning' },
    missing: { label: '未配置', tone: 'neutral' },
    failed: { label: '失败', tone: 'danger' },
  },
  review: {
    pending: { label: '待审核', tone: 'info' },
    approved: { label: '已通过', tone: 'success' },
    dismissed: { label: '已忽略', tone: 'neutral' },
    rejected: { label: '已拒绝', tone: 'danger' },
    failed: { label: '失败', tone: 'danger' },
  },
}

export function statusMeta(domain: StatusDomain, value: string | null | undefined): StatusMeta {
  if (!value) return { label: '-', tone: 'neutral' }
  return STATUS_MAP[domain][value] ?? { label: value, tone: 'neutral' }
}

// RN 下载器返回的失败原因码 → 中文说明
const DOWNLOADER_ERROR_TEXT: Record<string, string> = {
  channel_unavailable: '频道不可访问（可能已被封禁或转为私有）',
  not_found: '消息已不存在（可能已被删除）',
  telegram_refetch_failed: '重新获取 Telegram 消息失败（多为网络问题，可重试）',
  download_failed: '下载失败',
  upload_failed: '上传失败',
  unknown_package_size: '资源包大小未知，无法下载',
  package_exceeds_disk_capacity: '磁盘空间不足',
  cancelled: '已取消',
  callback_failed: '下载器内部错误',
  task_identity_conflict: '下载器内部错误（任务冲突）',
}

export const DOWNLOADER_UNKNOWN_ERROR_TEXT = 'RN 未提供原因（可能消息已删除或频道不可访问）'

export function downloaderErrorText(code: string | null | undefined): string {
  if (!code) return DOWNLOADER_UNKNOWN_ERROR_TEXT
  return DOWNLOADER_ERROR_TEXT[code] ?? code
}
