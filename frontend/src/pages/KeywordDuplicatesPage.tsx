import { useState } from 'react'
import { Alert, Button, Card, Col, InputNumber, Row, Select, Space, Tag, Typography, message } from 'antd'
import { LinkOutlined, MergeOutlined, SearchOutlined } from '@ant-design/icons'
import { api } from '@/api/client'
import type { KeywordDuplicatePair, KeywordDuplicateScanResponse } from '@/api/types'

const { Paragraph, Text, Title } = Typography

const TYPE_OPTIONS = [
  { label: '全部类型', value: '' },
  { label: '白名单', value: 'whitelist' },
  { label: '黑名单', value: 'blacklist' },
  { label: '忽略名', value: 'ignore' },
  { label: '标签', value: 'tag' },
]

export default function KeywordDuplicatesPage() {
  const [keywordType, setKeywordType] = useState<string>('')
  const [threshold, setThreshold] = useState(0.85)
  const [pairs, setPairs] = useState<KeywordDuplicatePair[]>([])
  const [loading, setLoading] = useState(false)
  const [mergingKey, setMergingKey] = useState<string | null>(null)

  const loadPairs = async () => {
    setLoading(true)
    try {
      const response = await api.post<KeywordDuplicateScanResponse>('/keywords/duplicates/scan', {
        keyword_type: keywordType || null,
        threshold,
      })
      setPairs(response.pairs ?? [])
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const mergePair = async (canonicalId: number, mergeId: number) => {
    const mergeKey = `${canonicalId}-${mergeId}`
    setMergingKey(mergeKey)
    try {
      await api.post('/keywords/merge', {
        canonical_entry_id: canonicalId,
        merge_entry_ids: [mergeId],
      })
      message.success(`已合并到关键词 #${canonicalId}`)
      setPairs((current) =>
        current.filter(
          (pair) =>
            !(
              (pair.keyword_1.id === canonicalId && pair.keyword_2.id === mergeId) ||
              (pair.keyword_1.id === mergeId && pair.keyword_2.id === canonicalId)
            ),
        ),
      )
    } catch (error: unknown) {
      message.error((error as Error).message)
    } finally {
      setMergingKey(null)
    }
  }

  return (
    <div className="page-shell">
      <div className="page-header">
        <div>
          <Title level={4} style={{ margin: 0 }}>重复词扫描</Title>
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            对现有关键词库做高相似度摸底，快速发现应该合并的标准词。
          </Paragraph>
        </div>
        <a href="/api/keywords/duplicates/workbench" target="_blank" rel="noreferrer">
          <Button icon={<LinkOutlined />}>旧版扫描台</Button>
        </a>
      </div>

      <Card className="soft-card" style={{ marginBottom: 16 }}>
        <Space wrap size={12}>
          <Select
            value={keywordType}
            style={{ width: 160 }}
            options={TYPE_OPTIONS}
            onChange={setKeywordType}
          />
          <InputNumber
            min={0.1}
            max={1}
            step={0.05}
            value={threshold}
            onChange={(value) => setThreshold(Number(value ?? 0.85))}
          />
          <Button type="primary" icon={<SearchOutlined />} onClick={loadPairs} loading={loading}>
            开始扫描
          </Button>
          <Text type="secondary">阈值越高，结果越保守。</Text>
        </Space>
      </Card>

      {!pairs.length && !loading && (
        <Alert
          type="info"
          showIcon
          message="还没有扫描结果。"
          description="建议先从白名单开始，阈值 0.85 比较稳。"
        />
      )}

      <div className="card-stack">
        {pairs.map((pair) => {
          const mergeLeftKey = `${pair.keyword_1.id}-${pair.keyword_2.id}`
          const mergeRightKey = `${pair.keyword_2.id}-${pair.keyword_1.id}`

          return (
            <Card key={`${pair.keyword_1.id}-${pair.keyword_2.id}`} className="soft-card">
              <div className="duplicate-card-header">
                <Text strong>发现可疑重合对</Text>
                <Tag color="orange">相似度 {(pair.score * 100).toFixed(0)}%</Tag>
              </div>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={11}>
                  <Card size="small">
                    <Text strong>{`#${pair.keyword_1.id} · ${pair.keyword_1.canonical_name}`}</Text>
                    <div className="meta-tags">
                      <Tag>{pair.keyword_1.keyword_type}</Tag>
                      <Tag>{pair.keyword_1.status}</Tag>
                      <Tag>{`别名 ${pair.keyword_1.aliases.length}`}</Tag>
                    </div>
                    <Text type="secondary">{pair.keyword_1.note || '无备注'}</Text>
                  </Card>
                </Col>
                <Col xs={24} md={2} className="duplicate-divider">
                  <MergeOutlined />
                </Col>
                <Col xs={24} md={11}>
                  <Card size="small">
                    <Text strong>{`#${pair.keyword_2.id} · ${pair.keyword_2.canonical_name}`}</Text>
                    <div className="meta-tags">
                      <Tag>{pair.keyword_2.keyword_type}</Tag>
                      <Tag>{pair.keyword_2.status}</Tag>
                      <Tag>{`别名 ${pair.keyword_2.aliases.length}`}</Tag>
                    </div>
                    <Text type="secondary">{pair.keyword_2.note || '无备注'}</Text>
                  </Card>
                </Col>
              </Row>
              <Space wrap style={{ marginTop: 16 }}>
                <Button
                  type="primary"
                  loading={mergingKey === mergeLeftKey}
                  onClick={() => mergePair(pair.keyword_1.id, pair.keyword_2.id)}
                >
                  {`将 [${pair.keyword_2.canonical_name}] 合并到左侧`}
                </Button>
                <Button
                  loading={mergingKey === mergeRightKey}
                  onClick={() => mergePair(pair.keyword_2.id, pair.keyword_1.id)}
                >
                  {`将 [${pair.keyword_1.canonical_name}] 合并到右侧`}
                </Button>
              </Space>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
