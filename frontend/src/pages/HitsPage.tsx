import { useCallback, useEffect, useState } from 'react'
import {
  Select, Button, Switch, Space, Typography, Card, message, Descriptions,
  Table, Tag, Input, Alert, Divider,
} from 'antd'
import { FireOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { api } from '@/api/client'
import type {
  TreeImport, ImportListResponse,
  KeywordHit,
  KeywordHitRebuildResponse,
  TreeHitSummaryItem, TreeHitSummaryResponse,
} from '@/api/types'

const { Title, Text } = Typography

export default function HitsPage() {
  const [imports, setImports]         = useState<TreeImport[]>([])
  const [importId, setImportId]       = useState<number | null>(null)

  // 重建命中
  const [inclFolders, setInclFolders] = useState(true)
  const [inclFiles, setInclFiles]     = useState(false)
  const [replaceExist, setReplaceExist] = useState(true)
  const [rebuilding, setRebuilding]   = useState(false)
  const [rebuildResult, setRebuildResult] = useState<KeywordHitRebuildResponse | null>(null)

  // tree-hit-summary
  const [treePath, setTreePath]       = useState('')
  const [typeFilter, setTypeFilter]   = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [summaryQ, setSummaryQ]       = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryItems, setSummaryItems] = useState<TreeHitSummaryItem[]>([])
  const [summaryTotal, setSummaryTotal] = useState(0)
  const [hitsLoading, setHitsLoading] = useState(false)
  const [hits, setHits] = useState<KeywordHit[]>([])

  useEffect(() => {
    api.get<ImportListResponse>('/imports/data?limit=100')
      .then((d) => setImports(d.items ?? []))
      .catch(() => {})
  }, [])

  // 重建命中
  const rebuildHits = async () => {
    if (!importId) { message.warning('请先选择导入批次'); return }
    setRebuilding(true)
    setRebuildResult(null)
    try {
      const res = await api.post<KeywordHitRebuildResponse>('/keywords/hits/rebuild', {
        import_id: importId,
        include_folders: inclFolders,
        include_files: inclFiles,
        replace_existing: replaceExist,
      })
      setRebuildResult(res)
      message.success(`命中重建完成：命中 ${res.created_count} 条，匹配关键词 ${res.matched_keyword_count} 个`)
      loadSummary()
      loadHits()
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setRebuilding(false)
    }
  }

  // 加载 tree-hit-summary
  const loadSummary = useCallback(async () => {
    if (!importId) return
    setSummaryLoading(true)
    try {
      const params = new URLSearchParams({ import_id: String(importId), limit: '200' })
      if (treePath)    params.set('tree_path', treePath)
      if (typeFilter)  params.set('keyword_type', typeFilter)
      if (statusFilter) params.set('status', statusFilter)
      if (summaryQ)    params.set('query', summaryQ)
      const data = await api.get<TreeHitSummaryResponse>(`/keywords/tree-hit-summary?${params}`)
      setSummaryItems(data.items ?? [])
      setSummaryTotal(data.total ?? 0)
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setSummaryLoading(false)
    }
  }, [importId, treePath, typeFilter, statusFilter, summaryQ])

  const loadHits = useCallback(async () => {
    if (!importId) return
    setHitsLoading(true)
    try {
      const params = new URLSearchParams({ import_id: String(importId), limit: '50' })
      const data = await api.get<KeywordHit[]>(`/keywords/hits?${params}`)
      setHits(data ?? [])
    } catch (e: unknown) {
      message.error((e as Error).message)
    } finally {
      setHitsLoading(false)
    }
  }, [importId])

  useEffect(() => {
    if (!importId) return
    void loadSummary()
    void loadHits()
  }, [importId, loadHits, loadSummary])

  const TYPE_COLOR: Record<string, string> = {
    whitelist: 'green', blacklist: 'red', ignore: 'orange', tag: 'blue',
  }

  const summaryColumns: ColumnsType<TreeHitSummaryItem> = [
    { title: 'ID', dataIndex: 'keyword_entry_id', width: 65 },
    { title: '关键词', dataIndex: 'canonical_name', ellipsis: true },
    {
      title: '类型', dataIndex: 'keyword_type', width: 100,
      render: (v: string) => <Tag color={TYPE_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (v: string) => <Tag color={v === 'active' ? 'green' : 'default'}>{v}</Tag>,
    },
    { title: '命中数', dataIndex: 'hit_count', width: 80 },
    {
      title: '示例路径', dataIndex: 'sample_paths',
      render: (paths: string[]) => (
        <div style={{ fontSize: 12, color: '#666' }}>
          {paths.slice(0, 3).map((p, i) => <div key={i} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 300 }}>{p}</div>)}
        </div>
      ),
    },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 16 }}>命中重建</Title>

      {/* 批次选择 */}
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <span style={{ fontWeight: 500 }}>导入批次：</span>
          <Select
            placeholder="选择批次"
            style={{ width: 280 }}
            options={imports.map((i) => ({ value: i.id, label: `#${i.id} · ${i.source_filename}` }))}
            onChange={(v: number) => { setImportId(v); setRebuildResult(null) }}
            allowClear
          />
        </Space>
      </Card>

      {!importId && (
        <Alert message="请先选择导入批次，再执行命中重建或查看命中排行。" type="info" showIcon />
      )}

      {importId && (
        <>
          {/* 命中重建 */}
          <Card
            title={<Space><FireOutlined style={{ color: '#fa8c16' }} /><span>关键词命中重建</span></Space>}
            style={{ marginBottom: 16 }}
          >
            <Space wrap style={{ marginBottom: 12 }}>
              <Space>
                <span>扫描目录：</span>
                <Switch checked={inclFolders} onChange={setInclFolders} checkedChildren="是" unCheckedChildren="否" />
              </Space>
              <Space>
                <span>扫描文件：</span>
                <Switch checked={inclFiles} onChange={setInclFiles} checkedChildren="是" unCheckedChildren="否" />
              </Space>
              <Space>
                <span>替换已有命中：</span>
                <Switch checked={replaceExist} onChange={setReplaceExist} checkedChildren="是" unCheckedChildren="否" />
              </Space>
              <Button type="primary" icon={<FireOutlined />} loading={rebuilding} onClick={rebuildHits}>
                开始重建
              </Button>
            </Space>

            {rebuildResult && (
              <Descriptions bordered size="small" column={3}>
                <Descriptions.Item label="删除旧命中">{rebuildResult.deleted_count}</Descriptions.Item>
                <Descriptions.Item label="新建命中">{rebuildResult.created_count}</Descriptions.Item>
                <Descriptions.Item label="匹配关键词">{rebuildResult.matched_keyword_count}</Descriptions.Item>
                <Descriptions.Item label="扫描目录数">{rebuildResult.scanned_folder_count}</Descriptions.Item>
                <Descriptions.Item label="扫描文件数">{rebuildResult.scanned_file_count}</Descriptions.Item>
              </Descriptions>
            )}
          </Card>

          {/* tree-hit-summary */}
          <Card title="关键词命中排行">
            <Space wrap style={{ marginBottom: 12 }}>
              <Input
                placeholder="路径前缀过滤（如 /根目录/待整理）"
                style={{ width: 280 }}
                allowClear
                value={treePath}
                onChange={(e) => setTreePath(e.target.value)}
                onPressEnter={() => loadSummary()}
              />
              <Select
                placeholder="类型" allowClear style={{ width: 110 }}
                options={['whitelist','blacklist','ignore','tag'].map((v) => ({ value: v, label: v }))}
                onChange={(v: string | undefined) => setTypeFilter(v)}
              />
              <Select
                placeholder="状态" allowClear style={{ width: 100 }}
                options={['active','disabled'].map((v) => ({ value: v, label: v }))}
                onChange={(v: string | undefined) => setStatusFilter(v)}
              />
              <Input.Search
                placeholder="搜索关键词"
                allowClear
                style={{ width: 180 }}
                onSearch={(v) => setSummaryQ(v)}
                onChange={(e) => { if (!e.target.value) setSummaryQ('') }}
              />
              <Button onClick={loadSummary} loading={summaryLoading}>刷新</Button>
              <span style={{ color: '#888', fontSize: 13 }}>共 {summaryTotal} 个关键词命中</span>
            </Space>
            <Divider style={{ margin: '0 0 12px' }} />
            <Table
              rowKey="keyword_entry_id"
              dataSource={summaryItems}
              columns={summaryColumns}
              loading={summaryLoading}
              size="small"
              pagination={{ pageSize: 50, showTotal: (t) => `共 ${t} 条` }}
            />
          </Card>

          <Card title="最近命中记录" style={{ marginTop: 16 }}>
            {!hits.length && !hitsLoading && (
              <Alert message="当前批次还没有命中记录。" type="info" showIcon />
            )}
            <div className="card-stack">
              {hits.map((hit) => (
                <Card key={hit.id} size="small">
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                    <Text strong>{hit.raw_keyword}</Text>
                    <div className="meta-tags">
                      <Tag>{hit.canonical_name_snapshot || '未归并'}</Tag>
                      <Tag>{hit.match_source}</Tag>
                    </div>
                  </div>
                  <div className="ellipsis-stack">
                    <div>{hit.source_path}</div>
                  </div>
                </Card>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
