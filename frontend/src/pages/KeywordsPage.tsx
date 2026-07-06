import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { MergeOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import type {
  KeywordEntry,
  KeywordEntryCreatePayload,
  KeywordEntryListResponse,
  KeywordMergePolicy,
  KeywordOperationLog,
  SimilarKeywordPreviewResponse,
} from '@/api/types'
import DataToolbar from '@/layout/DataToolbar'
import { formatDateTime, splitTextareaLines } from '@/utils/format'

const { Paragraph, Text, Title } = Typography

const TYPE_COLOR: Record<string, string> = {
  whitelist: 'green',
  blacklist: 'red',
  ignore: 'orange',
  tag: 'blue',
  emby_blacklist: 'volcano',
  emby_whitelist: 'cyan',
}

// keyword_type 中文标签；emby_* 由 emby 元数据功能写入共用表，需能正常展示
const TYPE_LABEL: Record<string, string> = {
  whitelist: '白名单',
  blacklist: '黑名单',
  ignore: '忽略名',
  tag: '标签',
  emby_blacklist: 'Emby 黑名单',
  emby_whitelist: 'Emby 白名单',
}

const TYPE_OPTIONS = [
  { label: '白名单', value: 'whitelist' },
  { label: '黑名单', value: 'blacklist' },
  { label: '忽略名', value: 'ignore' },
  { label: '标签', value: 'tag' },
]

const MERGE_POLICY_OPTIONS: Array<{ label: string; value: KeywordMergePolicy; help: string }> = [
  { label: '普通', value: 'normal', help: '可参与组合目录' },
  { label: '低优先级', value: 'fallback_only', help: '仅在没有其他普通白名单命中时生效' },
]

const MERGE_POLICY_LABEL: Record<KeywordMergePolicy, string> = {
  normal: '普通',
  fallback_only: '低优先级',
}

export default function KeywordsPage() {
  const [entries, setEntries] = useState<KeywordEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [logs, setLogs] = useState<KeywordOperationLog[]>([])
  const [selectedRowKeys, setSelectedRowKeys] = useState<Array<string | number>>([])
  const [mergeEntryIds, setMergeEntryIds] = useState('')
  const [canonicalEntryId, setCanonicalEntryId] = useState<number | null>(null)
  const [similarKeywords, setSimilarKeywords] = useState('')
  const [similarLoading, setSimilarLoading] = useState(false)
  const [similarResult, setSimilarResult] = useState<SimilarKeywordPreviewResponse | null>(null)
  const [query, setQuery] = useState('')
  const [queryDraft, setQueryDraft] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [createForm] = Form.useForm<KeywordEntryCreatePayload>()
  const [editForm] = Form.useForm<{
    canonical_name: string
    keyword_type: KeywordEntry['keyword_type']
    merge_policy: KeywordMergePolicy
    note: string | null
  }>()
  const [aliasForm] = Form.useForm<{ aliases: string }>()
  const [editingEntry, setEditingEntry] = useState<KeywordEntry | null>(null)
  const [aliasEntry, setAliasEntry] = useState<KeywordEntry | null>(null)
  const pageSize = 20

  const loadEntries = useCallback(async (nextPage = page) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        skip: String((nextPage - 1) * pageSize),
        limit: String(pageSize),
      })
      if (query) {
        params.set('query', query)
      }
      if (typeFilter) {
        params.set('keyword_type', typeFilter)
      }
      if (statusFilter) {
        params.set('status', statusFilter)
      }
      const response = await api.get<KeywordEntryListResponse>(`/keywords?${params.toString()}`)
      setEntries(response.entries ?? [])
      setTotal(response.total ?? 0)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, query, statusFilter, typeFilter])

  const loadLogs = useCallback(async () => {
    try {
      const response = await api.get<KeywordOperationLog[]>('/keywords/operation-logs?limit=20')
      setLogs(response ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadLogs()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [loadLogs])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1)
      void loadEntries(1)
    }, 0)

    return () => window.clearTimeout(timer)
  }, [loadEntries, query, typeFilter, statusFilter])

  const resetKeywordSelection = () => {
    setSelectedRowKeys([])
    setMergeEntryIds('')
  }

  const handleCreate = async (values: KeywordEntryCreatePayload) => {
    try {
      await api.post('/keywords', {
        ...values,
        merge_policy: values.merge_policy ?? 'normal',
        aliases: values.aliases,
        note: values.note?.trim() || null,
      })
      message.success(`已创建关键词 ${values.canonical_name}`)
      createForm.resetFields()
      await Promise.all([loadEntries(1), loadLogs()])
      setPage(1)
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const handleUpdate = async (values: {
    canonical_name: string
    keyword_type: KeywordEntry['keyword_type']
    merge_policy: KeywordMergePolicy
    note: string | null
  }) => {
    if (!editingEntry) {
      return
    }
    try {
      await api.patch(`/keywords/${editingEntry.id}`, {
        canonical_name: values.canonical_name.trim(),
        keyword_type: values.keyword_type,
        merge_policy: values.merge_policy,
        note: values.note?.trim() || null,
      })
      setEditingEntry(null)
      message.success('关键词已更新')
      await Promise.all([loadEntries(page), loadLogs()])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const handleAddAliases = async (values: { aliases: string }) => {
    if (!aliasEntry) {
      return
    }
    try {
      await api.post(`/keywords/${aliasEntry.id}/aliases`, {
        aliases: splitTextareaLines(values.aliases),
      })
      aliasForm.resetFields()
      setAliasEntry(null)
      message.success('别名已添加')
      await Promise.all([loadEntries(page), loadLogs()])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const updateStatus = async (entry: KeywordEntry, nextStatus: string) => {
    try {
      await api.patch(`/keywords/${entry.id}`, { status: nextStatus })
      message.success(nextStatus === 'active' ? '已启用' : '已禁用')
      await Promise.all([loadEntries(page), loadLogs()])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const deleteEntry = async (entryId: number) => {
    try {
      await api.delete(`/keywords/${entryId}`)
      message.success(`关键词 #${entryId} 已删除`)
      await Promise.all([loadEntries(page), loadLogs()])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const loadAllFilteredIds = async () => {
    try {
      const params = new URLSearchParams({ skip: '0', limit: String(Math.max(total, pageSize, 500)) })
      if (query) {
        params.set('query', query)
      }
      if (typeFilter) {
        params.set('keyword_type', typeFilter)
      }
      if (statusFilter) {
        params.set('status', statusFilter)
      }
      const response = await api.get<KeywordEntryListResponse>(`/keywords?${params.toString()}`)
      const ids = (response.entries ?? []).map((item) => item.id)
      setSelectedRowKeys(ids)
      message.success(`已全选当前筛选结果，共 ${ids.length} 项`)
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const appendMergeIds = () => {
    const current = new Set(
      mergeEntryIds
        .split(',')
        .map((item) => Number(item.trim()))
        .filter(Boolean),
    )

    selectedRowKeys
      .map(Number)
      .filter((id) => id !== canonicalEntryId)
      .forEach((id) => current.add(id))

    const mergedIds = [...current].sort((left, right) => left - right)
    setMergeEntryIds(mergedIds.join(', '))
    message.success(mergedIds.length ? '已加入待合并 ID' : '没有可加入的条目')
  }

  const mergeKeywords = async () => {
    const mergeIds = mergeEntryIds
      .split(',')
      .map((item) => Number(item.trim()))
      .filter(Boolean)

    if (!canonicalEntryId || !mergeIds.length) {
      message.warning('请先填写保留标准词 ID 和待合并 ID')
      return
    }

    try {
      await api.post('/keywords/merge', {
        canonical_entry_id: canonicalEntryId,
        merge_entry_ids: mergeIds,
      })
      message.success(`已合并到关键词 #${canonicalEntryId}`)
      resetKeywordSelection()
      await Promise.all([loadEntries(page), loadLogs()])
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }

  const checkSimilar = async () => {
    const keywords = splitTextareaLines(similarKeywords)
    if (!keywords.length) {
      message.warning('请先输入待检查关键词')
      return
    }

    setSimilarLoading(true)
    try {
      const response = await api.post<SimilarKeywordPreviewResponse>('/keywords/similar-preview', {
        keywords,
        threshold: 0.75,
        limit: 50,
      })
      setSimilarResult(response)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setSimilarLoading(false)
    }
  }

  const columns: ColumnsType<KeywordEntry> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '关键词',
      dataIndex: 'canonical_name',
      render: (value: string, record) => {
        const mergePolicy = record.merge_policy ?? 'normal'

        return (
          <div>
            <Text strong>{value}</Text>
            <div className="meta-tags">
              <Tag color={TYPE_COLOR[record.keyword_type] ?? 'default'}>{TYPE_LABEL[record.keyword_type] ?? record.keyword_type}</Tag>
              <Tag color={record.status === 'active' ? 'green' : 'default'}>{record.status}</Tag>
              <Tag color={mergePolicy === 'fallback_only' ? 'gold' : 'default'}>
                {MERGE_POLICY_LABEL[mergePolicy]}
              </Tag>
              <Tag>{`别名 ${record.aliases.length}`}</Tag>
            </div>
            <Text type="secondary">{record.note || '无备注'}</Text>
          </div>
        )
      },
    },
    {
      title: '别名',
      dataIndex: 'aliases',
      render: (aliases) => (
        <div className="meta-tags">
          {aliases.map((alias: KeywordEntry['aliases'][number]) => (
            <Tag key={alias.id}>{alias.alias}</Tag>
          ))}
        </div>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: '操作',
      width: 260,
      render: (_value, record) => (
        <Space wrap>
          <Button
            size="small"
            onClick={() => {
              setEditingEntry(record)
              editForm.setFieldsValue({
                canonical_name: record.canonical_name,
                keyword_type: record.keyword_type,
                merge_policy: record.merge_policy ?? 'normal',
                note: record.note,
              })
            }}
          >
            编辑
          </Button>
          <Button
            size="small"
            onClick={() => {
              setAliasEntry(record)
              aliasForm.resetFields()
            }}
          >
            加别名
          </Button>
          {record.status === 'active' ? (
            <Button size="small" onClick={() => updateStatus(record, 'disabled')}>禁用</Button>
          ) : (
            <Button size="small" onClick={() => updateStatus(record, 'active')}>启用</Button>
          )}
          <Button size="small" danger onClick={() => deleteEntry(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="page-shell">
      <div className="page-header">
        <div>
          <Title level={4} style={{ margin: 0 }}>关键词管理台</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            恢复手动新增、别名维护、合并、命中重建、相似词提示和命中回查，回到旧版治理节奏。
          </Paragraph>
        </div>
        <Space wrap>
          <Link to="/hits">
            <Button>命中中心</Button>
          </Link>
          <a href="/keyword-duplicates">
            <Button icon={<MergeOutlined />}>重复词扫描</Button>
          </a>
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={8}>
          <Card className="soft-card" title="手动新增">
            <Form
              form={createForm}
              layout="vertical"
              initialValues={{ keyword_type: 'whitelist', merge_policy: 'normal', aliases: [] }}
              onFinish={handleCreate}
            >
              <Form.Item name="canonical_name" label="标准名称" rules={[{ required: true, message: '请输入标准名称' }]}>
                <Input />
              </Form.Item>
              <Form.Item name="keyword_type" label="类型" rules={[{ required: true }]}>
                <Select options={TYPE_OPTIONS} />
              </Form.Item>
              <Form.Item
                name="merge_policy"
                label="整理优先级"
                rules={[{ required: true, message: '请选择整理优先级' }]}
              >
                <Select
                  options={MERGE_POLICY_OPTIONS.map(({ label, value }) => ({ label, value }))}
                />
              </Form.Item>
              <Text type="secondary">
                低优先级关键词只在没有其他普通白名单命中时参与整理；修改后需重新生成整理任务才会生效。
              </Text>
              <Form.Item
                name="aliases"
                label="别名（每行一个）"
                getValueFromEvent={(event) => splitTextareaLines(event.target.value)}
                getValueProps={(value?: string[]) => ({ value: (value ?? []).join('\n') })}
              >
                <Input.TextArea rows={4} />
              </Form.Item>
              <Form.Item name="note" label="备注">
                <Input.TextArea rows={3} />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />}>新增关键词</Button>
            </Form>
          </Card>

          <Card className="soft-card" title="合并关键词" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Input
                type="number"
                value={canonicalEntryId ?? undefined}
                onChange={(event) => setCanonicalEntryId(Number(event.target.value) || null)}
                placeholder="保留标准词 ID"
              />
              <Input
                value={mergeEntryIds}
                onChange={(event) => setMergeEntryIds(event.target.value)}
                placeholder="待合并 ID，逗号分隔"
              />
              <Space wrap>
                <Button onClick={appendMergeIds}>将勾选项加入待合并</Button>
                <Button onClick={resetKeywordSelection}>清空勾选</Button>
              </Space>
              <Button type="primary" icon={<MergeOutlined />} onClick={mergeKeywords}>
                执行合并
              </Button>
              <Text type="secondary">
                当前勾选：{selectedRowKeys.length ? selectedRowKeys.join(', ') : '暂无'}
              </Text>
            </Space>
          </Card>

          <Card className="soft-card" title="相似提示" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Input.TextArea
                rows={5}
                value={similarKeywords}
                onChange={(event) => setSimilarKeywords(event.target.value)}
                placeholder="每行一个关键词"
              />
              <Button onClick={checkSimilar} loading={similarLoading}>检查相似词</Button>
              <div className="card-stack">
                {(similarResult?.suggestions ?? []).map((item) => (
                  <Card key={`${item.keyword}-${item.matched_entry_id}`} size="small">
                    <Text strong>{item.keyword}</Text>
                    <div className="meta-tags">
                      <Tag color="gold">{item.matched_canonical_name}</Tag>
                      <Tag>{`${(item.score * 100).toFixed(0)}%`}</Tag>
                    </div>
                  </Card>
                ))}
                {!similarResult?.suggestions?.length && <Text type="secondary">相似词提示会显示在这里。</Text>}
              </div>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={16}>
          <Card className="soft-card" title="关键词列表">
            <div style={{ marginBottom: 12 }}>
              <DataToolbar>
                <Input.Search
                  allowClear
                  style={{ width: 240 }}
                  placeholder="搜索标准名或别名"
                  value={queryDraft}
                  onChange={(event) => {
                    setQueryDraft(event.target.value)
                    if (!event.target.value) {
                      setQuery('')
                    }
                  }}
                  onSearch={(value) => setQuery(value.trim())}
                />
                <Select
                  allowClear
                  style={{ width: 140 }}
                  placeholder="类型"
                  options={TYPE_OPTIONS}
                  value={typeFilter}
                  onChange={setTypeFilter}
                />
                <Select
                  allowClear
                  style={{ width: 140 }}
                  placeholder="状态"
                  options={[
                    { label: 'active', value: 'active' },
                    { label: 'disabled', value: 'disabled' },
                  ]}
                  value={statusFilter}
                  onChange={setStatusFilter}
                />
                <Button icon={<ReloadOutlined />} onClick={() => loadEntries(page)} loading={loading}>刷新</Button>
                <Button onClick={loadAllFilteredIds}>全选当前筛选结果</Button>
                <Text type="secondary">{`共 ${total} 条`}</Text>
              </DataToolbar>
            </div>
            <Table
              rowKey="id"
              dataSource={entries}
              columns={columns}
              loading={loading}
              rowSelection={{
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys as Array<string | number>),
              }}
              pagination={{
                current: page,
                pageSize,
                total,
                onChange: (nextPage) => {
                  setPage(nextPage)
                  loadEntries(nextPage)
                },
                showTotal: (value) => `共 ${value} 条`,
              }}
            />
          </Card>

          <Card className="soft-card" title="最近操作日志" style={{ marginTop: 16 }}>
            {!logs.length && (
              <Alert type="info" showIcon message="还没有操作日志。" />
            )}
            <div className="card-stack">
              {logs.map((log) => (
                <Card key={log.id} size="small">
                  <Text strong>{log.action}</Text>
                  <div className="meta-tags">
                    {log.keyword_entry_id && <Tag>{`主词 #${log.keyword_entry_id}`}</Tag>}
                    {log.related_keyword_entry_id && <Tag>{`相关 #${log.related_keyword_entry_id}`}</Tag>}
                    <Tag>{formatDateTime(log.created_at)}</Tag>
                  </div>
                  <Text type="secondary">{log.detail || '无补充信息'}</Text>
                </Card>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      <Modal
        title={editingEntry ? `编辑关键词 #${editingEntry.id}` : '编辑关键词'}
        open={!!editingEntry}
        okText="保存"
        onCancel={() => setEditingEntry(null)}
        onOk={() => editForm.submit()}
      >
        <Form form={editForm} layout="vertical" onFinish={handleUpdate}>
          <Form.Item name="canonical_name" label="标准名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="keyword_type" label="类型" rules={[{ required: true }]}>
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="merge_policy"
            label="整理优先级"
            rules={[{ required: true, message: '请选择整理优先级' }]}
          >
            <Select options={MERGE_POLICY_OPTIONS.map(({ label, value }) => ({ label, value }))} />
          </Form.Item>
          <Text type="secondary">
            低优先级关键词只在没有其他普通白名单命中时参与整理；修改后需重新生成整理任务才会生效。
          </Text>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={4} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={aliasEntry ? `为 #${aliasEntry.id} 添加别名` : '添加别名'}
        open={!!aliasEntry}
        okText="保存"
        onCancel={() => setAliasEntry(null)}
        onOk={() => aliasForm.submit()}
      >
        <Form form={aliasForm} layout="vertical" onFinish={handleAddAliases}>
          <Form.Item name="aliases" label="别名（每行一个）" rules={[{ required: true }]}>
            <Input.TextArea rows={5} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
