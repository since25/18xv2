import { useCallback, useEffect, useState } from 'react'
import {
  Table, Select, Button, Tag, Space, Typography, Card, message,
  Collapse, Modal, Form, Input, Popconfirm, Switch, Alert, Radio,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { api } from '@/api/client'
import type {
  OrganizeTask, TreeImport, ImportListResponse,
  DupConflictGroup, DupConflictListResponse,
  TaskBatchResponse, PlanBatchResponse,
  AmbiguousConflictListResponse, AmbiguousResolveResponse,
  NodeDetailItem, NodeDetailResponse,
  FileInfoItem, FileInfoResponse,
  DuplicateResolveResponse,
} from '@/api/types'

const { Title } = Typography

const STATUS_COLOR: Record<string, string> = {
  pending: 'blue', completed: 'green', failed: 'red', skipped: 'default',
}

export default function OrganizeTasksPage() {
  const [imports, setImports]           = useState<TreeImport[]>([])
  const [importId, setImportId]         = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [tasks, setTasks]               = useState<OrganizeTask[]>([])
  const [loading, setLoading]           = useState(false)

  // 重复目标冲突
  const [dupConflicts, setDupConflicts] = useState<DupConflictListResponse | null>(null)
  const [dupLoading, setDupLoading]     = useState(false)
  // 第一层：节点详情 { taskId: NodeDetailItem }
  const [nodeDetails, setNodeDetails]   = useState<Record<number, NodeDetailItem>>({})
  const [nodeDetailsLoading, setNodeDetailsLoading] = useState<Record<number, boolean>>({})
  // 第二层：115 文件信息 { cid: FileInfoItem }
  const [fileInfo, setFileInfo]         = useState<Record<string, FileInfoItem>>({})
  const [fileInfoLoading, setFileInfoLoading] = useState(false)
  // 重复冲突裁决：{ [target_path]: { keepId, deleteFrom115 } }
  const [dupSelections, setDupSelections] = useState<Record<string, { keepId: number; deleteFrom115: boolean }>>({})
  const [dupSubmitting, setDupSubmitting] = useState(false)

  // 歧义冲突内联
  const [ambigConflicts, setAmbigConflicts] = useState<AmbiguousConflictListResponse | null>(null)
  const [ambigLoading, setAmbigLoading]     = useState(false)
  // 用户裁决：{ [source_path]: keyword_entry_id }
  const [ambigSelections, setAmbigSelections] = useState<Record<string, number>>({})
  const [ambigSubmitting, setAmbigSubmitting] = useState(false)

  // 手动生成任务
  const [manualKwId, setManualKwId]     = useState('')
  const [manualTarget, setManualTarget] = useState('/根目录/已整理/')

  // 勾选 & 计划生成
  const [selectedIds, setSelectedIds]   = useState<number[]>([])

  // 改路径弹窗
  const [editTask, setEditTask]         = useState<OrganizeTask | null>(null)
  const [editForm]                      = Form.useForm()

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api.get<ImportListResponse>('/imports/data?limit=100')
        .then((d) => setImports(d.items ?? []))
        .catch(() => {})
    }, 0)

    return () => window.clearTimeout(timer)
  }, [])

  const loadTasks = useCallback(async () => {
    if (!importId) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ import_id: String(importId) })
      if (statusFilter) params.set('status', statusFilter)
      const data = await api.get<OrganizeTask[]>(`/organize-tasks?${params}`)
      setTasks(data)
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [importId, statusFilter])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadTasks()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [loadTasks])

  const rebuildTasks = async () => {
    if (!importId) return
    setLoading(true)
    try {
      const res = await api.post<TaskBatchResponse>('/organize-tasks/generate-from-import', {
        import_id: importId, replace_existing: true,
      })
      message.success(`重建完成：新建 ${res.created_count} 条，跳过歧义 ${res.skipped_ambiguous_count} 条`)
      setSelectedIds([])
      loadTasks()
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const generateFromKeyword = async () => {
    if (!importId) { message.warning('请先选择批次'); return }
    const kwId = parseInt(manualKwId)
    if (!kwId) { message.warning('请输入关键词 ID'); return }
    if (!manualTarget.trim()) { message.warning('请输入目标根目录'); return }
    try {
      const res = await api.post<TaskBatchResponse>('/organize-tasks/generate-from-keyword', {
        import_id: importId,
        keyword_entry_id: kwId,
        target_root: manualTarget.trim(),
        replace_existing: true,
      })
      message.success(`按关键词生成完成：新建 ${res.created_count} 条`)
      loadTasks()
    } catch (e: unknown) {
      message.error((e as Error).message)
    }
  }

  // ── 歧义冲突内联 ─────────────────────────────────────────────

  const loadAmbigConflicts = async () => {
    if (!importId) return
    setAmbigLoading(true)
    try {
      const res = await api.get<AmbiguousConflictListResponse>(`/organize-tasks/ambiguous-conflicts?import_id=${importId}`)
      setAmbigConflicts(res)
      // 默认预选每条路径的第一个关键词
      const defaults: Record<string, number> = {}
      for (const item of res.items) {
        if (item.keyword_options.length > 0) defaults[item.source_path] = item.keyword_options[0].id
      }
      setAmbigSelections(defaults)
    } catch (e: unknown) { message.error((e as Error).message) }
    finally { setAmbigLoading(false) }
  }

  const submitAmbigResolutions = async () => {
    if (!importId || !ambigConflicts) return
    setAmbigSubmitting(true)
    try {
      const resolutions = ambigConflicts.items
        .filter(item => ambigSelections[item.source_path] != null)
        .map(item => ({ source_path: item.source_path, keyword_entry_id: ambigSelections[item.source_path] }))
      const res = await api.post<AmbiguousResolveResponse>('/organize-tasks/ambiguous-conflicts/resolve', {
        import_id: importId, resolutions, replace_existing: true,
      })
      message.success(`歧义裁决完成：新建 ${res.created_count} 条，替换 ${res.replaced_count} 条`)
      loadTasks()
      setAmbigConflicts(null)
    } catch (e: unknown) { message.error((e as Error).message) }
    finally { setAmbigSubmitting(false) }
  }

  // ── 重复目标冲突三层懒加载 ─────────────────────────────────────

  const loadDupConflicts = async () => {
    if (!importId) return
    setDupLoading(true)
    try {
      const res = await api.get<DupConflictListResponse>(`/organize-tasks/duplicate-conflicts?import_id=${importId}`)
      setDupConflicts(res)
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setDupLoading(false)
    }
  }

  // 第一层：按组懒加载节点详情，跳过已缓存的
  const loadNodeDetails = async (taskIds: number[]) => {
    const missing = taskIds.filter(id => !(id in nodeDetails))
    if (!missing.length) return
    setNodeDetailsLoading(prev => Object.fromEntries([...Object.entries(prev), ...missing.map(id => [id, true])]))
    try {
      const res = await api.post<NodeDetailResponse>('/organize-tasks/node-details', { task_ids: missing })
      setNodeDetails(prev => {
        const next = { ...prev }
        for (const [k, v] of Object.entries(res.details)) next[Number(k)] = v
        return next
      })
    } catch (e: unknown) { message.error((e as Error).message) }
    finally {
      setNodeDetailsLoading(prev => Object.fromEntries(Object.entries(prev).map(([k, _]) => [k, false])))
    }
  }

  // 第二层：按 cid 懒加载 115 文件信息，跳过已缓存的
  const loadFileInfo = async (cids: string[]) => {
    const missing = cids.filter(c => !(c in fileInfo))
    if (!missing.length) return
    setFileInfoLoading(true)
    try {
      const res = await api.post<FileInfoResponse>('/115/file-info', { cids: missing })
      setFileInfo(prev => ({ ...prev, ...res.results }))
    } catch (e: unknown) { message.error((e as Error).message) }
    finally { setFileInfoLoading(false) }
  }

  const submitDupResolutions = async () => {
    if (!dupConflicts) return
    setDupSubmitting(true)
    try {
      const resolutions = dupConflicts.groups
        .filter(g => dupSelections[g.target_path]?.keepId != null)
        .map(g => {
          const { keepId, deleteFrom115 } = dupSelections[g.target_path]
          return {
            target_path: g.target_path,
            keep_task_id: keepId,
            skip_task_ids: g.tasks.filter(t => t.id !== keepId).map(t => t.id),
            delete_from_115: deleteFrom115,
          }
        })
      if (!resolutions.length) { message.warning('请先选择要保留的任务'); return }
      const res = await api.post<DuplicateResolveResponse>('/organize-tasks/resolve-duplicate-conflicts', { resolutions })
      const errMsg = res.errors.length ? `，${res.errors.length} 个错误: ${res.errors.slice(0, 2).join(' | ')}` : ''
      message.success(`处理完成：${res.resolved_count} 组冲突已解决，删除 ${res.deleted_from_115_count} 个${errMsg}`)
      setDupConflicts(null)
      setDupSelections({})
      loadTasks()
    } catch (e: unknown) { message.error((e as Error).message) }
    finally { setDupSubmitting(false) }
  }

  // ── 任务列表操作 ──────────────────────────────────────────────

  const skipTask = async (id: number) => {
    try {
      await api.patch(`/organize-tasks/${id}`, { status: 'skipped' })
      message.success(`任务 #${id} 已跳过`)
      loadTasks()
      if (dupConflicts) loadDupConflicts()
    } catch (e: unknown) { message.error((e as Error).message) }
  }

  const saveTaskTarget = async (id: number, target_path: string) => {
    try {
      await api.patch(`/organize-tasks/${id}`, { target_path })
      message.success('目标路径已更新')
      setEditTask(null)
      loadTasks()
      if (dupConflicts) loadDupConflicts()
    } catch (e: unknown) { message.error((e as Error).message) }
  }

  const generatePlan = async () => {
    if (!importId || !selectedIds.length) { message.warning('请先勾选任务'); return }
    try {
      const res = await api.post<PlanBatchResponse>('/plans/generate-from-tasks', {
        import_id: importId,
        task_ids: [...selectedIds].sort((a, b) => a - b),
        dry_run: true,
      })
      message.success(`生成 ${res.total} 个计划，首个 ID: #${res.plans[0]?.id}，请到「整理计划」页执行`)
      setSelectedIds([])
    } catch (e: unknown) { message.error((e as Error).message) }
  }

  const taskCols: ColumnsType<OrganizeTask> = [
    { title: 'ID', dataIndex: 'id', width: 65 },
    { title: '关键词', dataIndex: 'matched_canonical_name', width: 130, ellipsis: true },
    {
      title: '状态', dataIndex: 'status', width: 85,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    { title: '来源路径', dataIndex: 'source_path', ellipsis: true },
    { title: '目标路径', dataIndex: 'target_path', ellipsis: true },
    {
      title: '操作', width: 120,
      render: (_: unknown, r: OrganizeTask) => (
        <Space size={4}>
          <Button size="small" onClick={() => { setEditTask(r); editForm.setFieldValue('target_path', r.target_path) }}>改路径</Button>
          <Popconfirm title="跳过此任务？" onConfirm={() => skipTask(r.id)}>
            <Button size="small" danger>跳过</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const grouped = tasks.reduce<Record<string, OrganizeTask[]>>((acc, t) => {
    const k = t.matched_canonical_name ?? '未命名'
    ;(acc[k] ??= []).push(t)
    return acc
  }, {})

  return (
    <div>
      {/* 顶部工具栏 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Title level={4} style={{ margin: 0 }}>整理任务</Title>
        <Select
          placeholder="选择批次" style={{ width: 240 }} allowClear
          options={imports.map((i) => ({ value: i.id, label: `#${i.id} · ${i.source_filename}` }))}
          onChange={(v: number | undefined) => { setImportId(v ?? null); setDupConflicts(null) }}
        />
        <Select
          placeholder="状态筛选" style={{ width: 115 }} allowClear
          options={['pending','completed','failed','skipped'].map((v) => ({ value: v, label: v }))}
          onChange={(v: string | undefined) => setStatusFilter(v ?? null)}
        />
        <Button onClick={rebuildTasks} disabled={!importId} loading={loading} type="primary">
          重建任务
        </Button>
        <Button onClick={() => { setSelectedIds(tasks.map((t) => t.id)); message.info(`已全选 ${tasks.length} 条`) }}>
          全选
        </Button>
        <Button onClick={() => setSelectedIds([])}>清空勾选</Button>
        <Button type="primary" ghost onClick={generatePlan} disabled={!selectedIds.length}>
          从勾选任务生成计划 ({selectedIds.length})
        </Button>
      </Space>

      {!importId && <Alert message="请先选择导入批次。" type="info" showIcon style={{ marginBottom: 16 }} />}

      {importId && (
        <>
          {/* 歧义冲突内联 Radio 选择 */}
          <Card
            size="small"
            title="歧义冲突处理（多关键词命中同一路径）"
            style={{ marginBottom: 12 }}
            extra={<Button size="small" onClick={loadAmbigConflicts} loading={ambigLoading}>加载歧义冲突</Button>}
          >
            {!ambigConflicts && <span style={{ color: '#888', fontSize: 13 }}>点击右上角「加载歧义冲突」查看。</span>}
            {ambigConflicts && ambigConflicts.conflict_count === 0 && <span style={{ color: '#52c41a' }}>✓ 当前批次无歧义冲突。</span>}
            {ambigConflicts && ambigConflicts.conflict_count > 0 && (
              <>
                <div style={{ marginBottom: 8, color: '#888', fontSize: 13 }}>
                  共 {ambigConflicts.conflict_count} 条歧义路径，请为每条选择归属关键词：
                </div>
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  {ambigConflicts.items.map(item => (
                    <Card key={item.source_path} size="small" style={{ background: '#fafafa' }}>
                      <div style={{ fontFamily: 'monospace', fontSize: 12, marginBottom: 6 }}>{item.source_path}</div>
                      <Radio.Group
                        value={ambigSelections[item.source_path]}
                        onChange={(e) => setAmbigSelections(prev => ({ ...prev, [item.source_path]: e.target.value }))}
                      >
                        <Space direction="vertical">
                          {item.keyword_options.map(opt => (
                            <Radio key={opt.id} value={opt.id}>{opt.name} (ID: {opt.id})</Radio>
                          ))}
                        </Space>
                      </Radio.Group>
                    </Card>
                  ))}
                </Space>
                <div style={{ marginTop: 12 }}>
                  <Button
                    type="primary"
                    onClick={submitAmbigResolutions}
                    loading={ambigSubmitting}
                    disabled={ambigConflicts.items.some(item => ambigSelections[item.source_path] == null)}
                  >
                    保存裁决并生成任务
                  </Button>
                </div>
              </>
            )}
          </Card>

          {/* 重复目标冲突三层懒加载 */}
          <Card size="small" style={{ marginBottom: 12 }}
            title="重复目标冲突（同一目标路径被多个任务占用）"
            extra={<Button size="small" onClick={loadDupConflicts} loading={dupLoading}>检查冲突</Button>}
          >
            {!dupConflicts && <span style={{ color: '#888', fontSize: 13 }}>点击右上角「检查冲突」查看。</span>}
            {dupConflicts && dupConflicts.conflict_count === 0 && <span style={{ color: '#52c41a' }}>✓ 当前批次无重复目标冲突。</span>}
            {dupConflicts && dupConflicts.conflict_count > 0 && (
              <>
                <Collapse size="small" style={{ marginTop: 8 }}
                  onChange={(keys) => {
                    // 展开某个分组时，懒加载该组的节点详情
                    const activeKeys = Array.isArray(keys) ? keys : [keys]
                    for (const key of activeKeys) {
                      const idx = Number(key)
                      const group = dupConflicts.groups[idx]
                      if (group) loadNodeDetails(group.tasks.map(t => t.id))
                    }
                  }}
                  items={dupConflicts.groups.map((g: DupConflictGroup, i: number) => ({
                    key: i,
                    label: <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{g.target_path} <Tag color="red">{g.tasks.length} 条冲突</Tag></span>,
                    children: (
                      <div>
                        <Radio.Group
                          value={dupSelections[g.target_path]?.keepId}
                          onChange={(e) => setDupSelections(prev => ({
                            ...prev,
                            [g.target_path]: { ...prev[g.target_path], keepId: e.target.value, deleteFrom115: prev[g.target_path]?.deleteFrom115 ?? false }
                          }))}
                        >
                          <Space direction="vertical" style={{ width: '100%' }}>
                            {g.tasks.map(t => {
                              const detail = nodeDetails[t.id]
                              const fi = detail?.cid ? fileInfo[detail.cid] : undefined
                              return (
                                <Radio key={t.id} value={t.id}>
                                  <Space direction="vertical" size={2}>
                                    <span>任务 #{t.id} · {t.source_path}</span>
                                    {detail && (
                                      <span style={{ fontSize: 12, color: '#888' }}>
                                        节点: {detail.raw_name} · {detail.raw_path}
                                        {detail.cid && <> · cid: {detail.cid}</>}
                                      </span>
                                    )}
                                    {detail?.cid && fi && !fi.error && (
                                      <span style={{ fontSize: 12, color: '#888' }}>
                                        大小: {fi.size != null ? `${(fi.size / 1024 / 1024).toFixed(1)} MB` : '未知'} · 修改时间: {fi.modified_at ?? '未知'}
                                      </span>
                                    )}
                                    {fi?.error && <span style={{ fontSize: 12, color: 'red' }}>{fi.error}</span>}
                                  </Space>
                                </Radio>
                              )
                            })}
                          </Space>
                        </Radio.Group>
                        <Space style={{ marginTop: 8 }} size={12}>
                          <Button
                            size="small"
                            loading={g.tasks.some(t => nodeDetailsLoading[t.id])}
                            onClick={() => loadNodeDetails(g.tasks.map(t => t.id))}
                          >
                            查看本地详情
                          </Button>
                          <Button
                            size="small"
                            loading={fileInfoLoading}
                            disabled={!g.tasks.some(t => nodeDetails[t.id]?.cid)}
                            onClick={() => {
                              const cids = g.tasks.map(t => nodeDetails[t.id]?.cid).filter((c): c is string => c != null)
                              loadFileInfo(cids)
                            }}
                          >
                            从 115 刷新
                          </Button>
                          <Space size={4}>
                            <span style={{ fontSize: 12 }}>删除被跳过的 115 目录：</span>
                            <Switch
                              size="small"
                              checked={dupSelections[g.target_path]?.deleteFrom115 ?? false}
                              onChange={(v) => setDupSelections(prev => ({
                                ...prev,
                                [g.target_path]: { ...prev[g.target_path], keepId: prev[g.target_path]?.keepId, deleteFrom115: v }
                              }))}
                            />
                          </Space>
                        </Space>
                      </div>
                    ),
                  }))}
                />
                <div style={{ marginTop: 12 }}>
                  <Button type="primary" danger onClick={submitDupResolutions} loading={dupSubmitting}>
                    确认处理所有冲突
                  </Button>
                </div>
              </>
            )}
          </Card>

          {/* 手动生成 */}
          <Card size="small" title="手动按关键词生成任务（用于歧义裁决后）" style={{ marginBottom: 12 }}>
            <Space wrap>
              <Input
                placeholder="关键词 ID（数字）"
                style={{ width: 160 }}
                value={manualKwId}
                onChange={(e) => setManualKwId(e.target.value)}
              />
              <Input
                placeholder="目标根目录"
                style={{ width: 240 }}
                value={manualTarget}
                onChange={(e) => setManualTarget(e.target.value)}
              />
              <Button onClick={generateFromKeyword}>按关键词生成</Button>
            </Space>
          </Card>
        </>
      )}

      {/* 任务列表 */}
      <Card title={`任务列表（按关键词分组，共 ${tasks.length} 条）`}>
        {!tasks.length && !loading && (
          <div style={{ color: '#888', padding: 8 }}>
            {importId ? '当前批次暂无整理任务，请点击「重建任务」。' : '请先选择导入批次。'}
          </div>
        )}
        {Object.entries(grouped)
          .sort(([a], [b]) => a.localeCompare(b, 'zh-CN'))
          .map(([kw, items]) => (
            <Collapse key={kw} size="small" style={{ marginBottom: 6 }}
              items={[{
                key: kw,
                label: <span>{kw} <Tag>{items.length} 条</Tag></span>,
                children: (
                  <Table<OrganizeTask>
                    rowKey="id"
                    dataSource={items}
                    columns={taskCols}
                    size="small"
                    pagination={false}
                    rowSelection={{
                      selectedRowKeys: selectedIds,
                      onChange: (keys) => setSelectedIds(keys as number[]),
                    }}
                  />
                ),
              }]}
            />
          ))}
      </Card>

      {/* 改路径弹窗 */}
      <Modal
        title="修改目标路径"
        open={!!editTask}
        onOk={() => editForm.submit()}
        onCancel={() => setEditTask(null)}
        okText="保存"
      >
        <Form form={editForm} onFinish={(v: { target_path: string }) => editTask && saveTaskTarget(editTask.id, v.target_path)}>
          <Form.Item name="target_path" label="新目标路径" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
