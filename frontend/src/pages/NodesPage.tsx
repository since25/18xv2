import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Input, InputNumber, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { ImportListResponse, TreeImport, TreeImportEntry, TreeImportEntryListResponse } from '@/api/types'

const { Paragraph, Title, Text } = Typography

export default function NodesPage() {
  const [searchParams] = useSearchParams()
  const [imports, setImports] = useState<TreeImport[]>([])
  const [selectedImportId, setSelectedImportId] = useState<number | null>(
    searchParams.get('import_id') ? Number(searchParams.get('import_id')) : null,
  )
  const [query, setQuery] = useState('')
  const [maxDepth, setMaxDepth] = useState<number | null>(null)
  const [entries, setEntries] = useState<TreeImportEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loadingImports, setLoadingImports] = useState(false)
  const [loadingEntries, setLoadingEntries] = useState(false)

  const loadImports = useCallback(async () => {
    setLoadingImports(true)
    try {
      const response = await api.get<ImportListResponse>('/imports/data?limit=200')
      setImports(response.items ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoadingImports(false)
    }
  }, [])

  const loadEntries = useCallback(async () => {
    if (!selectedImportId) {
      setEntries([])
      setTotal(0)
      return
    }
    setLoadingEntries(true)
    try {
      const params = new URLSearchParams()
      if (query.trim()) {
        params.set('query', query.trim())
      }
      if (maxDepth !== null) {
        params.set('max_depth', String(maxDepth))
      }
      params.set('limit', '500')
      const response = await api.get<TreeImportEntryListResponse>(`/imports/${selectedImportId}/entries?${params.toString()}`)
      setEntries(response.items ?? [])
      setTotal(response.total ?? 0)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoadingEntries(false)
    }
  }, [maxDepth, query, selectedImportId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadImports()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadImports])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadEntries()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadEntries])

  const columns: ColumnsType<TreeImportEntry> = [
    {
      title: '名称',
      dataIndex: 'raw_name',
      render: (value: string, record) => (
        <div>
          <Text strong>{value}</Text>
          <div style={{ marginTop: 6 }}>
            <Tag color={record.entry_type === 'folder' ? 'blue' : 'green'}>{record.entry_type}</Tag>
            <Tag>{`depth ${record.depth}`}</Tag>
            {record.remote_id && <Tag>{record.remote_id}</Tag>}
          </div>
          <div style={{ marginTop: 6, color: '#6b7280', wordBreak: 'break-all' }}>{record.raw_path}</div>
        </div>
      ),
    },
    {
      title: '归一化名',
      dataIndex: 'normalized_name',
      width: 260,
      ellipsis: true,
    },
  ]

  return (
    <div>
      <div className="page-header">
        <div>
          <Title level={4} style={{ margin: 0 }}>目录树内容</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            这里可以查看每个导入批次里实际有哪些目录和文件，便于排查根目录拉取结果和本地去重命中项。
          </Paragraph>
        </div>
      </div>

      <Card className="soft-card" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            showSearch
            allowClear
            loading={loadingImports}
            style={{ width: 380 }}
            placeholder="选择一个目录树批次"
            optionFilterProp="label"
            value={selectedImportId ?? undefined}
            onChange={(value) => setSelectedImportId(value ?? null)}
            options={imports.map((item) => ({
              value: item.id,
              label: `#${item.id} · ${item.source_filename} [${item.source_type}]`,
            }))}
          />
          <Input
            style={{ width: 220 }}
            placeholder="路径 / 名称搜索"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onPressEnter={() => void loadEntries()}
          />
          <InputNumber
            style={{ width: 140 }}
            placeholder="最大层级"
            min={0}
            value={maxDepth ?? undefined}
            onChange={(value) => setMaxDepth(typeof value === 'number' ? value : null)}
          />
          <Button onClick={() => void loadEntries()} loading={loadingEntries}>
            刷新内容
          </Button>
        </Space>
      </Card>

      <Card
        className="soft-card"
        title={selectedImportId ? `批次 #${selectedImportId} 的目录内容` : '先选择批次'}
        extra={selectedImportId ? <Text type="secondary">{`共 ${total} 条`}</Text> : null}
      >
        <Table
          rowKey={(record) => `${record.entry_type}-${record.id}`}
          dataSource={entries}
          columns={columns}
          loading={loadingEntries}
          size="small"
          pagination={{ pageSize: 50, showSizeChanger: false, showTotal: (count) => `共 ${count} 条` }}
        />
      </Card>
    </div>
  )
}
