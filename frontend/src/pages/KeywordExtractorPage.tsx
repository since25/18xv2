import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { FileTextOutlined, LinkOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import type {
  DeleteResponse,
  ExtractedKeyword,
  ExtractedKeywordListResponse,
  ImportListResponse,
  KeywordEntry,
  KeywordEntryBatchImportPayload,
  KeywordEntryListResponse,
  ManualPathRegexExtractPayload,
  RegexExtractPreviewResponse,
  RegexMatchPreviewItem,
  SimilarKeywordPreviewResponse,
  TreeImport,
} from '@/api/types'
import { formatDateTime, splitTextareaLines } from '@/utils/format'

const { Paragraph, Text, Title } = Typography

type KeywordListType = 'whitelist' | 'ignore' | 'blacklist'

const MATCH_STATUS_COLOR: Record<string, string> = {
  new: 'blue',
  similar: 'gold',
  existing: 'green',
  ignored: 'default',
}

export default function KeywordExtractorPage() {
  const [searchParams] = useSearchParams()
  const [imports, setImports] = useState<TreeImport[]>([])
  const [importId, setImportId] = useState<number | null>(null)
  const [uploadingTree, setUploadingTree] = useState(false)
  const [manualKeywords, setManualKeywords] = useState('')
  const [manualLimit, setManualLimit] = useState(100)
  const [manualPath, setManualPath] = useState('')
  const [regexPattern, setRegexPattern] = useState('[【「『［\\[]([^】」』］\\]]+)[】」』］\\]]')
  const [groupIndex, setGroupIndex] = useState(1)
  const [regexFlags, setRegexFlags] = useState('')
  const [regexMinCount, setRegexMinCount] = useState(1)
  const [regexLimit, setRegexLimit] = useState(100)
  const [keywordFilter, setKeywordFilter] = useState('')
  const [keywordsLoading, setKeywordsLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [savingListType, setSavingListType] = useState<KeywordListType | null>(null)
  const [summary, setSummary] = useState<ExtractedKeywordListResponse | null>(null)
  const [activeSource, setActiveSource] = useState<'manual' | 'regex' | 'manual_path_regex'>('manual')
  const [preview, setPreview] = useState<RegexExtractPreviewResponse | null>(null)
  const [selectedKeywords, setSelectedKeywords] = useState<Array<string | number>>([])
  const [libraryEntries, setLibraryEntries] = useState<KeywordEntry[]>([])
  const [similarLoading, setSimilarLoading] = useState(false)
  const [similarSuggestions, setSimilarSuggestions] = useState<SimilarKeywordPreviewResponse | null>(null)

  const loadImports = useCallback(async (preferredId?: number | null) => {
    try {
      const response = await api.get<ImportListResponse>('/imports/data?limit=100')
      const items = response.items ?? []
      const importIdFromQuery = Number(searchParams.get('import_id') || '') || null
      setImports(items)
      setImportId((current) => {
        if (importIdFromQuery && items.some((item) => item.id === importIdFromQuery)) {
          return importIdFromQuery
        }
        if (preferredId && items.some((item) => item.id === preferredId)) {
          return preferredId
        }
        if (current && items.some((item) => item.id === current)) {
          return current
        }
        return items[0]?.id ?? null
      })
    } catch (error: unknown) {
      message.error((error as Error).message)
    }
  }, [searchParams])

  const loadLibrary = async () => {
    setLibraryLoading(true)
    try {
      const response = await api.get<KeywordEntryListResponse>('/keywords?limit=5000')
      setLibraryEntries(response.entries ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLibraryLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadImports()
      void loadLibrary()
    }, 0)

    return () => window.clearTimeout(timer)
  }, [loadImports])

  useEffect(() => {
    const keywords = selectedKeywords.map(String)
    let cancelled = false
    const timer = window.setTimeout(() => {
      if (!keywords.length) {
        setSimilarSuggestions(null)
        return
      }

      void (async () => {
        setSimilarLoading(true)
        try {
          const response = await api.post<SimilarKeywordPreviewResponse>('/keywords/similar-preview', {
            keywords,
            threshold: 0.75,
            limit: 50,
          })
          if (!cancelled) {
            setSimilarSuggestions(response)
          }
        } catch (error: unknown) {
          if (!cancelled) {
            message.error((error as Error).message)
          }
        } finally {
          if (!cancelled) {
            setSimilarLoading(false)
          }
        }
      })()
    }, 0)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [selectedKeywords])

  const importOptions = imports.map((item) => ({
    value: item.id,
    label: `#${item.id} · ${item.source_filename}`,
  }))

  const filteredKeywords = (summary?.keywords ?? []).filter((item) => {
    if (!keywordFilter.trim()) {
      return true
    }
    const needle = keywordFilter.trim().toLowerCase()
    return (
      item.keyword.toLowerCase().includes(needle) ||
      item.examples.some((example) => example.toLowerCase().includes(needle))
    )
  })

  const keywordCounts = libraryEntries.reduce<Record<string, number>>((accumulator, entry) => {
    accumulator[entry.keyword_type] = (accumulator[entry.keyword_type] ?? 0) + 1
    return accumulator
  }, {})

  const handleUploadTree = async (file: File) => {
    setUploadingTree(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const response = await api.postForm<TreeImport>('/imports/tree', form)
      message.success(`目录树导入完成，批次 #${response.id}`)
      await loadImports(response.id)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setUploadingTree(false)
    }
    return false
  }

  const loadKeywordFile = async (file: File) => {
    try {
      const text = await file.text()
      const merged = splitTextareaLines(text).join('\n')
      setManualKeywords(merged)
      message.success(`已导入 ${merged ? merged.split('\n').length : 0} 个关键词`)
    } catch (error) {
      message.error((error as Error).message)
    }
    return false
  }

  const runManualKeywords = async () => {
    if (!importId) {
      message.warning('请先选择导入批次')
      return
    }

    const keywords = splitTextareaLines(manualKeywords)
    if (!keywords.length) {
      message.warning('请先输入手动关键词')
      return
    }

    setKeywordsLoading(true)
    try {
      const response = await api.post<ExtractedKeywordListResponse>('/extractor/keywords/manual', {
        import_id: importId,
        keywords,
        limit: manualLimit,
      })
      setSummary(response)
      setActiveSource('manual')
      setSelectedKeywords([])
      message.success('手动关键词匹配完成')
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setKeywordsLoading(false)
    }
  }

  const buildRegexPayload = () => ({
    import_id: importId,
    pattern: regexPattern,
    group_index: groupIndex,
    flags: regexFlags.trim(),
    min_count: regexMinCount,
    limit: regexLimit,
  })

  const buildManualPathRegexPayload = (): ManualPathRegexExtractPayload => ({
    import_id: importId,
    raw_path: manualPath.trim(),
    pattern: regexPattern,
    flags: regexFlags.trim(),
    group_index: groupIndex,
    limit: regexLimit,
  })

  const fetchRegexSummary = async () => {
    return api.post<ExtractedKeywordListResponse>('/extractor/keywords/regex', buildRegexPayload())
  }

  const previewRegex = async () => {
    if (!importId) {
      message.warning('请先选择导入批次')
      return
    }

    setPreviewLoading(true)
    try {
      const previewResponse = await api.post<RegexExtractPreviewResponse>(
        '/extractor/keywords/regex-preview',
        buildRegexPayload(),
      )
      const summaryResponse = await fetchRegexSummary()
      setPreview(previewResponse)
      setSummary(summaryResponse)
      setActiveSource('regex')
      setSelectedKeywords([])
      message.success('正则预览完成')
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setPreviewLoading(false)
    }
  }

  const runRegexExtraction = async () => {
    if (!importId) {
      message.warning('请先选择导入批次')
      return
    }

    setKeywordsLoading(true)
    try {
      const response = await fetchRegexSummary()
      setSummary(response)
      setActiveSource('regex')
      setSelectedKeywords([])
      message.success('正则汇总完成')
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setKeywordsLoading(false)
    }
  }

  const runManualPathExtraction = async () => {
    if (!manualPath.trim()) {
      message.warning('请先粘贴手工路径')
      return
    }

    setPreviewLoading(true)
    setKeywordsLoading(true)
    try {
      const payload = buildManualPathRegexPayload()
      const [previewResponse, summaryResponse] = await Promise.all([
        api.post<RegexExtractPreviewResponse>('/extractor/keywords/manual-path-regex', payload),
        api.post<ExtractedKeywordListResponse>('/extractor/keywords/manual-path-regex/summary', payload),
      ])
      setPreview(previewResponse)
      setSummary(summaryResponse)
      setActiveSource('manual_path_regex')
      setSelectedKeywords([])
      message.success('手工路径提取完成')
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setPreviewLoading(false)
      setKeywordsLoading(false)
    }
  }

  const selectVisibleKeywords = () => {
    setSelectedKeywords(filteredKeywords.map((item) => item.keyword))
  }

  const saveKeywords = async (keywords: string[], listType: KeywordListType) => {
    if (!keywords.length) {
      message.warning('请先选择关键词')
      return
    }

    setSavingListType(listType)

    try {
      const keywordObjects = (summary?.keywords ?? []).filter((item) => keywords.includes(item.keyword))
      const payload: KeywordEntryBatchImportPayload = {
        keywords,
        keyword_type: listType,
        import_id: importId,
        source: activeSource,
        pattern: activeSource === 'manual' ? null : regexPattern,
        flags: activeSource === 'manual' ? null : regexFlags.trim(),
        examples_by_keyword: Object.fromEntries(keywordObjects.map((item) => [item.keyword, item.examples])),
        source_folder_name_by_keyword: Object.fromEntries(
          keywordObjects.map((item) => [
            item.keyword,
            item.examples[0] ? item.examples[0].split('/').filter(Boolean).slice(-1)[0] : item.keyword,
          ]),
        ),
      }

      const response = await api.post<DeleteResponse & { created_count: number; existing_count: number }>(
        '/keywords/import',
        payload,
      )

      const saved = new Set(keywords)
      setSummary((current) =>
        current
          ? {
              ...current,
              total_keywords: Math.max(0, current.total_keywords - saved.size),
              total_actionable_keywords: Math.max(0, current.total_actionable_keywords - saved.size),
              total_similar_keywords: current.keywords.filter(
                (item) => !saved.has(item.keyword) && item.match_status === 'similar',
              ).length,
              keywords: current.keywords.filter((item) => !saved.has(item.keyword)),
            }
          : current,
      )
      setPreview((current) =>
        current
          ? {
              ...current,
              total_actionable_matches: current.preview.filter(
                (item) => !saved.has(item.extracted_keyword),
              ).length,
              preview: current.preview.filter((item) => !saved.has(item.extracted_keyword)),
            }
          : current,
      )
      setSelectedKeywords((current) => current.filter((item) => !saved.has(String(item))))
      await loadLibrary()
      message.success(`已保存到 ${listType}，新增 ${response.created_count} 条，已存在 ${response.existing_count} 条`)
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setSavingListType(null)
    }
  }

  const keywordColumns: ColumnsType<ExtractedKeyword> = [
    {
      title: '关键词',
      dataIndex: 'keyword',
      width: 220,
      render: (value: string, record) => (
        <div>
          <Text strong>{value}</Text>
          <div className="meta-tags">
            <Tag color={MATCH_STATUS_COLOR[record.match_status] ?? 'default'}>
              {record.match_status}
            </Tag>
            <Tag>{`命中 ${record.count}`}</Tag>
            <Tag>{record.source}</Tag>
            {record.matched_canonical_name && <Tag color="gold">{`近似 ${record.matched_canonical_name}`}</Tag>}
          </div>
        </div>
      ),
    },
    {
      title: '示例路径',
      dataIndex: 'examples',
      render: (examples: string[]) => (
        <div className="ellipsis-stack">
          {examples.slice(0, 4).map((example) => (
            <div key={example}>{example}</div>
          ))}
        </div>
      ),
    },
    {
      title: '操作',
      width: 220,
      render: (_value, record) => (
        <Space wrap>
          <Button size="small" type="primary" onClick={() => saveKeywords([record.keyword], 'whitelist')}>
            存白名单
          </Button>
          <Button size="small" onClick={() => saveKeywords([record.keyword], 'ignore')}>
            存忽略
          </Button>
          <Button size="small" onClick={() => saveKeywords([record.keyword], 'blacklist')}>
            存黑名单
          </Button>
        </Space>
      ),
    },
  ]

  const previewColumns: ColumnsType<RegexMatchPreviewItem> = [
    {
      title: '提取关键词',
      dataIndex: 'extracted_keyword',
      width: 220,
      render: (value: string, record) => (
        <div>
          <Text strong>{value}</Text>
          <div className="meta-tags">
            <Tag color={MATCH_STATUS_COLOR[record.match_status] ?? 'default'}>
              {record.match_status}
            </Tag>
            {record.matched_canonical_name && <Tag color="gold">{`近似 ${record.matched_canonical_name}`}</Tag>}
          </div>
        </div>
      ),
    },
    { title: '目录名', dataIndex: 'folder_name', width: 240 },
    { title: '原始路径', dataIndex: 'raw_path' },
  ]

  const libraryColumns: ColumnsType<KeywordEntry> = [
    {
      title: '关键词',
      dataIndex: 'canonical_name',
      width: 220,
      render: (value: string, record) => (
        <div>
          <Text strong>{value}</Text>
          <div className="meta-tags">
            <Tag>{record.keyword_type}</Tag>
            <Tag>{record.status}</Tag>
            <Tag>{`别名 ${record.aliases.length}`}</Tag>
          </div>
        </div>
      ),
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
  ]

  return (
    <div className="page-shell">
      <div className="page-header">
        <div>
          <Title level={4} style={{ margin: 0 }}>关键词提取器</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            从目录树批量提取、筛选并入库关键词，恢复旧版从导入到治理的起始链路。
          </Paragraph>
        </div>
        <a href="/api/extractor/keywords/workbench" target="_blank" rel="noreferrer">
          <Button icon={<LinkOutlined />}>旧版提取器</Button>
        </a>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={8}>
          <Card className="soft-card" title="目录树导入">
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Upload beforeUpload={handleUploadTree} showUploadList={false} accept=".txt,.text">
                <Button icon={<UploadOutlined />} loading={uploadingTree}>上传目录树</Button>
              </Upload>
            </Space>
          </Card>

          <Card className="soft-card" title="手工路径提取" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Input.TextArea
                rows={5}
                value={manualPath}
                onChange={(event) => setManualPath(event.target.value)}
                placeholder="粘贴完整路径，例如 /Volumes/.../xxx.mp4"
              />
              <Text type="secondary">
                会直接对路径最后一段文件名应用右侧默认正则，并将结果送到右侧提取结果区做白名单/黑名单入库。
              </Text>
              <Button type="primary" onClick={runManualPathExtraction} loading={previewLoading || keywordsLoading}>
                提取
              </Button>
            </Space>
          </Card>

          <Card className="soft-card" title="手动关键词" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Upload beforeUpload={loadKeywordFile} showUploadList={false} accept=".txt,.text,.csv">
                <Button icon={<FileTextOutlined />}>导入关键词文件</Button>
              </Upload>
              <Input.TextArea
                rows={8}
                value={manualKeywords}
                onChange={(event) => setManualKeywords(event.target.value)}
                placeholder="每行一个关键词"
              />
              <InputNumber
                min={1}
                value={manualLimit}
                onChange={(value) => setManualLimit(Number(value ?? 100))}
              />
              <Button type="primary" onClick={runManualKeywords} loading={keywordsLoading}>
                运行手动匹配
              </Button>
            </Space>
          </Card>

          <Card className="soft-card" title="正则提取" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Space.Compact style={{ width: '100%' }}>
                <Select
                  value={importId ?? undefined}
                  style={{ width: '100%' }}
                  placeholder="选择导入批次"
                  options={importOptions}
                  onChange={(value) => setImportId(value)}
                  allowClear
                />
                <Button icon={<ReloadOutlined />} onClick={() => loadImports(importId)}>刷新批次</Button>
              </Space.Compact>
              <Alert
                type={importId ? 'success' : 'info'}
                showIcon
                message={importId ? `当前批次：#${importId}` : '当前未选择导入批次'}
                description="目录树正则提取需要选定批次；手工路径提取可直接使用，入库时会附带当前批次（如果已选择）。"
              />
              <Input value={regexPattern} onChange={(event) => setRegexPattern(event.target.value)} />
              <InputNumber
                min={0}
                value={groupIndex}
                onChange={(value) => setGroupIndex(Number(value ?? 1))}
              />
              <Input
                value={regexFlags}
                onChange={(event) => setRegexFlags(event.target.value)}
                placeholder="例如 i 或 im"
              />
              <InputNumber
                min={1}
                value={regexMinCount}
                onChange={(value) => setRegexMinCount(Number(value ?? 1))}
              />
              <InputNumber
                min={1}
                value={regexLimit}
                onChange={(value) => setRegexLimit(Number(value ?? 100))}
              />
              <Space wrap>
                <Button onClick={previewRegex} loading={previewLoading}>预览正则提取</Button>
                <Button type="primary" onClick={runRegexExtraction} loading={keywordsLoading}>
                  汇总正则结果
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={16}>
          <Card className="soft-card" title="提取结果">
            {!summary && (
              <Alert
                type="info"
                showIcon
                message="提取结果会显示在这里。"
                description="可以先手动匹配一批关键词、对目录树跑正则预览，或者直接粘贴一条完整路径做手工路径提取。"
              />
            )}

            {summary && (
              <>
                <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                  <Col xs={12} md={6}><Statistic title="扫描目录" value={summary.total_nodes} /></Col>
                  <Col xs={12} md={6}><Statistic title="待处理" value={summary.total_actionable_keywords} /></Col>
                  <Col xs={12} md={6}><Statistic title="已入库过滤" value={summary.total_existing_keywords} /></Col>
                  <Col xs={12} md={6}><Statistic title="相似待确认" value={summary.total_similar_keywords} /></Col>
                </Row>
                <Space wrap style={{ marginBottom: 12 }}>
                  <Input
                    allowClear
                    style={{ width: 260 }}
                    placeholder="筛选当前结果"
                    value={keywordFilter}
                    onChange={(event) => setKeywordFilter(event.target.value)}
                  />
                  <Button onClick={selectVisibleKeywords}>全选当前结果</Button>
                  <Button onClick={() => setSelectedKeywords([])}>清空勾选</Button>
                  <Button
                    type="primary"
                    loading={savingListType === 'whitelist'}
                    onClick={() => saveKeywords(selectedKeywords.map(String), 'whitelist')}
                  >
                    批量存白名单
                  </Button>
                  <Button
                    loading={savingListType === 'ignore'}
                    onClick={() => saveKeywords(selectedKeywords.map(String), 'ignore')}
                  >
                    批量存忽略
                  </Button>
                  <Button
                    loading={savingListType === 'blacklist'}
                    onClick={() => saveKeywords(selectedKeywords.map(String), 'blacklist')}
                  >
                    批量存黑名单
                  </Button>
                </Space>
                <Table
                  rowKey="keyword"
                  columns={keywordColumns}
                  dataSource={filteredKeywords}
                  loading={keywordsLoading}
                  pagination={{ pageSize: 10, showTotal: (total) => `共 ${total} 条` }}
                  rowSelection={{
                    selectedRowKeys: selectedKeywords,
                    onChange: (keys) => setSelectedKeywords(keys as Array<string | number>),
                  }}
                />
              </>
            )}
          </Card>

          <Card className="soft-card" title="正则预览" style={{ marginTop: 16 }}>
            {!preview && <Text type="secondary">正则命中的目录预览会显示在这里。</Text>}
            {preview && (
              <>
                <Descriptions bordered size="small" column={3} style={{ marginBottom: 16 }}>
                  <Descriptions.Item label="Pattern">{preview.pattern}</Descriptions.Item>
                  <Descriptions.Item label="Flags">{preview.flags || '-'}</Descriptions.Item>
                  <Descriptions.Item label="原始命中">{preview.total_matches}</Descriptions.Item>
                  <Descriptions.Item label="需人工处理">{preview.total_actionable_matches}</Descriptions.Item>
                  <Descriptions.Item label="扫描目录">{preview.total_nodes}</Descriptions.Item>
                  <Descriptions.Item label="来源">{activeSource}</Descriptions.Item>
                </Descriptions>
                <Table
                  rowKey={(item) => `${item.node_id}-${item.extracted_keyword}`}
                  columns={previewColumns}
                  dataSource={preview.preview}
                  loading={previewLoading}
                  pagination={{ pageSize: 8, showTotal: (total) => `共 ${total} 条` }}
                />
              </>
            )}
          </Card>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={14}>
              <Card className="soft-card" title="关键词库">
                <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                  <Col span={12}><Statistic title="白名单" value={keywordCounts.whitelist ?? 0} /></Col>
                  <Col span={12}><Statistic title="黑名单" value={keywordCounts.blacklist ?? 0} /></Col>
                  <Col span={12}><Statistic title="忽略名单" value={keywordCounts.ignore ?? 0} /></Col>
                  <Col span={12}><Statistic title="标签" value={keywordCounts.tag ?? 0} /></Col>
                </Row>
                <Button onClick={loadLibrary} loading={libraryLoading} style={{ marginBottom: 12 }}>
                  刷新关键词库
                </Button>
                <Table
                  rowKey="id"
                  columns={libraryColumns}
                  dataSource={libraryEntries.slice(0, 20)}
                  loading={libraryLoading}
                  size="small"
                  pagination={false}
                />
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card className="soft-card" title="相似匹配提示">
                {!selectedKeywords.length && (
                  <Alert type="info" showIcon message="勾选关键词后，这里会自动给出相似词提示。" />
                )}
                {selectedKeywords.length > 0 && (
                  <>
                    <Text type="secondary">当前勾选 {selectedKeywords.length} 项</Text>
                    <Table
                      rowKey={(item) => `${item.keyword}-${item.matched_entry_id}`}
                      dataSource={similarSuggestions?.suggestions ?? []}
                      loading={similarLoading}
                      size="small"
                      pagination={false}
                      columns={[
                        { title: '关键词', dataIndex: 'keyword' },
                        { title: '近似标准词', dataIndex: 'matched_canonical_name' },
                        {
                          title: '相似度',
                          dataIndex: 'score',
                          width: 90,
                          render: (value: number) => `${(value * 100).toFixed(0)}%`,
                        },
                      ]}
                    />
                  </>
                )}
              </Card>
            </Col>
          </Row>
        </Col>
      </Row>
    </div>
  )
}
