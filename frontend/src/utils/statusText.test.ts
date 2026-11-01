import { describe, expect, it } from 'vitest'
import { statusMeta } from './statusText'

describe('statusMeta', () => {
  it('maps package statuses', () => {
    expect(statusMeta('package', 'never')).toEqual({ label: '未下载', tone: 'neutral' })
    expect(statusMeta('package', 'queued')).toEqual({ label: '排队中', tone: 'info' })
    expect(statusMeta('package', 'downloading')).toEqual({ label: '下载中', tone: 'active' })
    expect(statusMeta('package', 'completed')).toEqual({ label: '已下载', tone: 'success' })
    expect(statusMeta('package', 'outdated')).toEqual({ label: '有更新', tone: 'warning' })
    expect(statusMeta('package', 'failed')).toEqual({ label: '下载异常', tone: 'danger' })
    expect(statusMeta('package', 'cancelled')).toEqual({ label: '已取消', tone: 'neutral' })
  })

  it('maps task and file statuses', () => {
    expect(statusMeta('task', 'pending')).toEqual({ label: '排队中', tone: 'info' })
    expect(statusMeta('task', 'completed_with_errors')).toEqual({ label: '部分完成', tone: 'warning' })
    expect(statusMeta('task', 'paused')).toEqual({ label: '已暂停', tone: 'warning' })
    expect(statusMeta('file', 'completed')).toEqual({ label: '已完成', tone: 'success' })
    expect(statusMeta('file', 'downloaded')).toEqual({ label: '已完成', tone: 'success' })
    expect(statusMeta('file', 'failed')).toEqual({ label: '失败', tone: 'danger' })
    expect(statusMeta('file', 'download_failed')).toEqual({ label: '失败', tone: 'danger' })
    expect(statusMeta('file', 'downloading')).toEqual({ label: '下载中', tone: 'active' })
    expect(statusMeta('file', 'pending')).toEqual({ label: '等待中', tone: 'info' })
    expect(statusMeta('file', 'upload_failed')).toEqual({ label: '上传失败', tone: 'danger' })
  })

  it('keeps unknown values readable and handles empty values', () => {
    expect(statusMeta('task', 'custom')).toEqual({ label: 'custom', tone: 'neutral' })
    expect(statusMeta('task', '')).toEqual({ label: '-', tone: 'neutral' })
    expect(statusMeta('task', null)).toEqual({ label: '-', tone: 'neutral' })
  })

  it('maps status domains used by the non-downloader pages', () => {
    const cases: Array<[Parameters<typeof statusMeta>[0], string, string]> = [
      ['import', 'done', '已完成'],
      ['import', 'running', '处理中'],
      ['keyword', 'active', '启用'],
      ['keyword', 'disabled', '停用'],
      ['keyword', 'similar', '相似'],
      ['workflow', 'planned', '已计划'],
      ['workflow', 'confirmed', '已确认'],
      ['workflow', 'dismissed', '已忽略'],
      ['workflow', 'blocked', '已阻塞'],
      ['auth', 'ok', '可用'],
      ['auth', 'invalid', '失效'],
      ['auth', 'expired', '已过期'],
      ['review', 'approved', '已通过'],
      ['review', 'rejected', '已拒绝'],
    ]
    for (const [domain, value, label] of cases) {
      expect(statusMeta(domain, value).label).toBe(label)
    }
  })

  it('covers every newly added status value', () => {
    const expected: Array<[Parameters<typeof statusMeta>[0], string]> = [
      ['import', 'pending'], ['import', 'running'], ['import', 'completed'], ['import', 'failed'],
      ['keyword', 'new'], ['keyword', 'matched'], ['keyword', 'ignored'], ['keyword', 'existing'], ['keyword', 'conflict'],
      ['workflow', 'pending_review'], ['workflow', 'queued'], ['workflow', 'running'], ['workflow', 'completed'],
      ['workflow', 'failed'], ['workflow', 'skipped'], ['workflow', 'draft'], ['workflow', 'applied'],
      ['workflow', 'cancelled'], ['workflow', 'submitted'], ['workflow', 'duplicate_skipped'], ['workflow', 'clear'],
      ['workflow', 'duplicate_found'], ['workflow', 'task_exists'], ['workflow', 'deleted'],
      ['auth', '0'], ['auth', '1'], ['auth', '2'], ['auth', '-1'], ['auth', '-2'], ['auth', '-3'],
      ['auth', 'polling'], ['auth', 'stopped'], ['auth', 'pending'], ['auth', 'valid'], ['auth', 'invalid'],
      ['auth', 'created'], ['auth', 'authorized'], ['auth', 'error'], ['auth', 'cooldown'], ['auth', 'reauth_required'], ['auth', 'missing'], ['auth', 'failed'],
      ['review', 'pending'], ['review', 'approved'], ['review', 'dismissed'], ['review', 'rejected'], ['review', 'failed'],
    ]
    for (const [domain, value] of expected) {
      expect(statusMeta(domain, value).label).not.toBe(value)
    }
  })
})
