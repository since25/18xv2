import { useState } from 'react'
import { Button, Card, Input, InputNumber, Select, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { ImportListResponse, TreeImport, TreeImportEntry, TreeImportEntryListResponse } from '@/api/types'
import DataToolbar from '@/layout/DataToolbar'
import PageScaffold from '@/layout/PageScaffold'
import { useApiQuery } from '@/hooks/useApiQuery'

const { Text } = Typography

export default function NodesPage() {
  const [searchParams] = useSearchParams()
  const [selectedImportId, setSelectedImportId] = useState<number | null>(
    searchParams.get('import_id') ? Number(searchParams.get('import_id')) : null,
  )
  const [query, setQuery] = useState('')
  const [maxDepth, setMaxDepth] = useState<number | null>(null)

  const { data: imports, loading: loadingImports } = useApiQuery(
    () => api.get<ImportListResponse>('/imports/data?limit=200').then((response) => response.items ?? []),
    [],
    { initialData: [] as TreeImport[] },
  )

  // 未选批次时不请求，列表显示为空
  const { data: entryPage, loading: loadingEntries, reload: reloadEntries } = useApiQuery(
    async () => {
      if (!selectedImportId) {
        return { items: [] as TreeImportEntry[], total: 0 }
      }
      const params = new URLSearchParams()
      if (query.trim()) {
        params.set('query', query.trim())
      }
      if (maxDepth !== null) {
        params.set('max_depth', String(maxDepth))
      }
      params.set('limit', '500')
      const response = await api.get<TreeImportEntryListResponse>(`/imports/${selectedImportId}/entries?${params.toString()}`)
      return { items: response.items ?? [], total: response.total ?? 0 }
    },
    [maxDepth, query, selectedImportId],
    { enabled: Boolean(selectedImportId), initialData: { items: [] as TreeImportEntry[], total: 0 } },
  )
  const entries = selectedImportId ? entryPage.items : []
  const total = selectedImportId ? entryPage.total : 0

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
          <Text type="secondary" style={{ display: 'block', marginTop: 6, wordBreak: 'break-all' }}>
            {record.raw_path}
          </Text>
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
    <PageScaffold
      title="目录树内容"
      titleLevel={4}
      description="这里可以查看每个导入批次里实际有哪些目录和文件，便于排查根目录拉取结果和本地去重命中项。"
    >

      <Card className="soft-card" style={{ marginBottom: 16 }}>
        <DataToolbar>
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
            onPressEnter={() => void reloadEntries()}
          />
          <InputNumber
            style={{ width: 140 }}
            placeholder="最大层级"
            min={0}
            value={maxDepth ?? undefined}
            onChange={(value) => setMaxDepth(typeof value === 'number' ? value : null)}
          />
          <Button onClick={() => void reloadEntries()} loading={loadingEntries}>
            刷新内容
          </Button>
        </DataToolbar>
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
    </PageScaffold>
  )
}
