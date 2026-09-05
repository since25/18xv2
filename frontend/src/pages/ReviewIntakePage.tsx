import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CheckOutlined,
  DeleteOutlined,
  InboxOutlined,
  ReloadOutlined,
  StopOutlined,
  UndoOutlined,
} from '@ant-design/icons'

import DataToolbar from '@/layout/DataToolbar'
import PageScaffold from '@/layout/PageScaffold'
import {
  approveReviewIntakeItem,
  createIgnoreKeyword,
  createReviewIntakeItem,
  deleteReviewIntakeItem,
  dismissReviewIntakeItem,
  getReviewIntakeSummary,
  listReviewIntakeItems,
  restoreReviewIntakeItem,
  type ReviewBucket,
  type ReviewIntakeItem,
  type ReviewIntakeSummary,
  type ReviewKeywordCandidate,
  type ReviewStatus,
} from '@/api/reviewIntake'

const BUCKET_OPTIONS: Array<{ label: string; value: ReviewBucket }> = [
  { label: '白名单', value: 'whitelist' },
  { label: '黑名单', value: 'blacklist' },
]

const STATUS_OPTIONS: Array<{ label: string; value: ReviewStatus | '' }> = [
  { label: '待审核', value: 'pending' },
  { label: '已批准', value: 'approved' },
  { label: '已忽略', value: 'dismissed' },
  { label: '全部', value: '' },
]

const MATCH_COLORS: Record<string, string> = {
  new: 'blue',
  similar: 'gold',
  existing: 'green',
  conflict: 'red',
  ignored: 'default',
}

// 面板顶部的颜色图例，省得记
const MATCH_LEGEND: Array<{ status: string; label: string }> = [
  { status: 'new', label: '新词' },
  { status: 'similar', label: '有相似词' },
  { status: 'existing', label: '库里已有' },
  { status: 'conflict', label: '冲突' },
  { status: 'ignored', label: '已忽略' },
]

// 行内平铺的候选个数，其余收进「更多」
const VISIBLE_CANDIDATES = 5

// 只有这两类来源是投稿者自己标出来的名字字段，才允许自动预填；
// 自由文本切片一律留空，避免噪声词被直接批准。
const PREFILL_SOURCES = new Set(['hashtag', 'bracket'])

// 提示组：不是"选它"，而是"这条可以跳过"或"点了会被拒"
const HINT_STATUSES = new Set(['existing', 'conflict'])

function isHint(candidate: ReviewKeywordCandidate) {
  return HINT_STATUSES.has(candidate.match_status)
}

// 和后端 normalize_keyword_text 保持一致的轻量归一化，用于「×」后本地去重移除
function normalizeWord(word: string) {
  return word
    .normalize('NFKC')
    .replace(/[_\-/]+/g, ' ')
    .replace(/[^\w\u4e00-\u9fff\s·]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

function defaultKeyword(item: ReviewIntakeItem) {
  // 只预填 hashtag / 括号来源的候选。自由文本切片排第一的往往是「抖音」这类
  // 噪声词，预填后用户不看就点批准会把噪声写进名单。
  const actionable = item.keyword_candidates.find(
    (candidate) =>
      ['new', 'similar'].includes(candidate.match_status) && PREFILL_SOURCES.has(candidate.source),
  )
  return item.approved_keyword ?? actionable?.keyword ?? ''
}

function itemLabel(item: ReviewIntakeItem) {
  return item.bucket === 'whitelist' ? '白名单' : '黑名单'
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function pathTooltip(rawPath: string) {
  return (
    <div className="review-path-tooltip">
      <div className="review-path-tooltip-label">完整路径/标题</div>
      <div>{rawPath}</div>
    </div>
  )
}

export default function ReviewIntakePage() {
  const [messageApi, contextHolder] = message.useMessage()
  const [bucket, setBucket] = useState<ReviewBucket>('whitelist')
  const [rawPath, setRawPath] = useState('')
  const [status, setStatus] = useState<ReviewStatus | ''>('pending')
  const [search, setSearch] = useState('')
  const [summary, setSummary] = useState<ReviewIntakeSummary | null>(null)
  const [whitelistItems, setWhitelistItems] = useState<ReviewIntakeItem[]>([])
  const [blacklistItems, setBlacklistItems] = useState<ReviewIntakeItem[]>([])
  const [keywordDrafts, setKeywordDrafts] = useState<Record<number, string>>({})
  const [expandedRows, setExpandedRows] = useState<Record<number, boolean>>({})
  const [hiddenWords, setHiddenWords] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const stats = useMemo(() => [
    { key: 'white-pending', label: '白待审', value: summary?.whitelist_pending ?? 0 },
    { key: 'black-pending', label: '黑待审', value: summary?.blacklist_pending ?? 0 },
    { key: 'approved', label: '已批准', value: (summary?.whitelist_approved ?? 0) + (summary?.blacklist_approved ?? 0) },
  ], [summary])

  function seedDrafts(items: ReviewIntakeItem[]) {
    setKeywordDrafts((current) => {
      const next = { ...current }
      for (const item of items) {
        if (next[item.id] === undefined) {
          next[item.id] = defaultKeyword(item)
        }
      }
      return next
    })
  }

  async function loadItems(nextSearch = search) {
    setLoading(true)
    try {
      const [white, black, nextSummary] = await Promise.all([
        listReviewIntakeItems({ bucket: 'whitelist', status, search: nextSearch || undefined, page_size: 200 }),
        listReviewIntakeItems({ bucket: 'blacklist', status, search: nextSearch || undefined, page_size: 200 }),
        getReviewIntakeSummary(),
      ])
      setWhitelistItems(white.items)
      setBlacklistItems(black.items)
      setSummary(nextSummary)
      seedDrafts([...white.items, ...black.items])
    } catch (error) {
      void messageApi.error(errorMessage(error, '加载待审核列表失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadItems()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  async function handleCreate() {
    if (!rawPath.trim()) {
      void messageApi.warning('请先粘贴路径')
      return
    }
    setSubmitting(true)
    try {
      const item = await createReviewIntakeItem({
        bucket,
        raw_path: rawPath,
        source: 'manual_web',
      })
      void messageApi.success(`已加入${itemLabel(item)}待审`)
      setRawPath('')
      await loadItems()
    } catch (error) {
      void messageApi.error(errorMessage(error, '投递失败'))
    } finally {
      setSubmitting(false)
    }
  }

  function pickKeyword(itemId: number, keyword: string) {
    setKeywordDrafts((current) => ({ ...current, [itemId]: keyword }))
  }

  async function handleIgnoreWord(word: string) {
    try {
      await createIgnoreKeyword(word)
      // 候选的状态色是投递那一刻算好存下来的，重新拉列表不会让它变灰，
      // 所以这里直接在本地把所有同名标签隐藏掉。
      setHiddenWords((current) => [...current, normalizeWord(word)])
      void messageApi.success(`已把「${word}」加入忽略库`)
    } catch (error) {
      void messageApi.error(errorMessage(error, '加入忽略库失败'))
    }
  }

  async function handleApprove(item: ReviewIntakeItem) {
    const keyword = (keywordDrafts[item.id] ?? '').trim()
    if (!keyword) {
      void messageApi.warning('请先确认关键词')
      return
    }
    try {
      await approveReviewIntakeItem(item.id, keyword, item.note)
      void messageApi.success(`已归入${itemLabel(item)}：${keyword}`)
      await loadItems()
    } catch (error) {
      void messageApi.error(errorMessage(error, '批准失败'))
    }
  }

  async function handleDismiss(item: ReviewIntakeItem) {
    try {
      await dismissReviewIntakeItem(item.id)
      void messageApi.success('已忽略')
      await loadItems()
    } catch (error) {
      void messageApi.error(errorMessage(error, '忽略失败'))
    }
  }

  async function handleRestore(item: ReviewIntakeItem) {
    try {
      await restoreReviewIntakeItem(item.id)
      void messageApi.success('已恢复为待审核')
      await loadItems()
    } catch (error) {
      void messageApi.error(errorMessage(error, '恢复失败'))
    }
  }

  async function handleDelete(item: ReviewIntakeItem) {
    try {
      await deleteReviewIntakeItem(item.id)
      void messageApi.success('已删除')
      await loadItems()
    } catch (error) {
      void messageApi.error(errorMessage(error, '删除失败'))
    }
  }

  function columnsFor(bucketType: ReviewBucket): ColumnsType<ReviewIntakeItem> {
    return [
      {
        title: '候选（点一下填入右侧）',
        dataIndex: 'keyword_candidates',
        width: 300,
        render: (_: unknown, item) => {
          const usable = item.keyword_candidates.filter(
            (candidate) => !hiddenWords.includes(normalizeWord(candidate.keyword)),
          )
          const hints = usable.filter(isHint)
          const picks = usable.filter((candidate) => !isHint(candidate))
          const expanded = expandedRows[item.id] ?? false
          const shown = expanded ? picks : picks.slice(0, VISIBLE_CANDIDATES)
          const restCount = picks.length - shown.length

          const renderTag = (candidate: ReviewKeywordCandidate, index: number) => {
            const canIgnore = ['new', 'similar'].includes(candidate.match_status)
            return (
              <Tooltip
                key={`${candidate.keyword}-${candidate.match_status}-${index}`}
                title={pathTooltip(item.raw_path)}
                mouseEnterDelay={1}
                placement="topLeft"
              >
                <Tag
                  className="review-candidate-tag review-candidate-tag--pickable"
                  color={MATCH_COLORS[candidate.match_status] ?? 'default'}
                  onClick={() => pickKeyword(item.id, candidate.keyword)}
                >
                  <span className="review-candidate-text">{candidate.keyword}</span>
                  {canIgnore ? (
                    <Popconfirm
                      title={`把「${candidate.keyword}」加入忽略库？`}
                      description="以后这个词不再作为候选出现"
                      onConfirm={() => void handleIgnoreWord(candidate.keyword)}
                    >
                      <span
                        className="review-candidate-drop"
                        title="加入忽略库"
                        onClick={(event) => event.stopPropagation()}
                      >
                        ×
                      </span>
                    </Popconfirm>
                  ) : null}
                </Tag>
              </Tooltip>
            )
          }

          if (!usable.length) {
            // 零候选行恰恰最需要看路径，悬停提示必须保留
            return (
              <Tooltip title={pathTooltip(item.raw_path)} mouseEnterDelay={1} placement="topLeft">
                <Tag className="review-candidate-tag" color="default">未提取</Tag>
              </Tooltip>
            )
          }

          return (
            <div className="review-candidate-cell">
              {hints.length ? (
                <div className="review-candidate-hints">
                  <span className="review-candidate-hint-label">已在库中：</span>
                  {hints.map(renderTag)}
                </div>
              ) : null}
              <Space className="review-candidate-tags" size={[4, 4]} wrap>
                {shown.map(renderTag)}
                {restCount > 0 ? (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => setExpandedRows((current) => ({ ...current, [item.id]: true }))}
                  >
                    更多 {restCount}
                  </Button>
                ) : null}
                {expanded && picks.length > VISIBLE_CANDIDATES ? (
                  <Button
                    size="small"
                    type="link"
                    onClick={() => setExpandedRows((current) => ({ ...current, [item.id]: false }))}
                  >
                    收起
                  </Button>
                ) : null}
              </Space>
            </div>
          )
        },
      },
      {
        title: '确认关键词',
        key: 'keyword',
        width: 170,
        render: (_: unknown, item) => (
          <Input
            size="small"
            value={keywordDrafts[item.id] ?? ''}
            onChange={(event) => {
              setKeywordDrafts((current) => ({ ...current, [item.id]: event.target.value }))
            }}
            placeholder={bucketType === 'whitelist' ? '白名单词' : '黑名单词'}
          />
        ),
      },
      {
        title: '状态',
        dataIndex: 'status',
        width: 90,
        render: (value: ReviewStatus) => {
          const color = value === 'pending' ? 'blue' : value === 'approved' ? 'green' : 'default'
          const label = value === 'pending' ? '待审' : value === 'approved' ? '已批准' : '已忽略'
          return <Tag color={color}>{label}</Tag>
        },
      },
      {
        title: '操作',
        key: 'actions',
        width: 116,
        render: (_: unknown, item) => (
          <Space className="review-action-buttons" size={4} wrap>
            {item.status !== 'approved' ? (
              <Tooltip title="批准">
                <Button
                  aria-label="批准"
                  size="small"
                  type="primary"
                  icon={<CheckOutlined />}
                  onClick={() => void handleApprove(item)}
                />
              </Tooltip>
            ) : null}
            {item.status === 'pending' ? (
              <Popconfirm title="忽略这条待审核项？" onConfirm={() => void handleDismiss(item)}>
                <Tooltip title="忽略">
                  <Button aria-label="忽略" size="small" icon={<StopOutlined />} />
                </Tooltip>
              </Popconfirm>
            ) : null}
            {item.status === 'dismissed' ? (
              <Tooltip title="恢复">
                <Button
                  aria-label="恢复"
                  size="small"
                  icon={<UndoOutlined />}
                  onClick={() => void handleRestore(item)}
                />
              </Tooltip>
            ) : null}
            <Popconfirm title="删除这条记录？" onConfirm={() => void handleDelete(item)}>
              <Tooltip title="删除">
                <Button aria-label="删除" size="small" danger icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          </Space>
        ),
      },
    ]
  }

  function renderPanel(title: string, bucketType: ReviewBucket, items: ReviewIntakeItem[]) {
    return (
      <Card
        className="soft-card review-intake-card"
        title={title}
        extra={<Tag color={bucketType === 'whitelist' ? 'green' : 'red'}>{items.length}</Tag>}
      >
        <div className="review-legend">
          {MATCH_LEGEND.map((entry) => (
            <Tag key={entry.status} color={MATCH_COLORS[entry.status]}>{entry.label}</Tag>
          ))}
        </div>
        {items.length ? (
          <Table
            size="small"
            rowKey="id"
            loading={loading}
            pagination={false}
            columns={columnsFor(bucketType)}
            dataSource={items}
            tableLayout="fixed"
            scroll={{ x: 676 }}
          />
        ) : (
          <Empty description="没有待处理记录" />
        )}
      </Card>
    )
  }

  return (
    <>
      {contextHolder}
      <PageScaffold
        title="待审核"
        description="快捷键投递会先进入这里；确认关键词后再写入正式黑白名单。"
        stats={stats}
        actions={<Button icon={<ReloadOutlined />} onClick={() => void loadItems()} loading={loading}>刷新</Button>}
      >
        <Card className="soft-card" title="手动投递">
          <Space direction="vertical" size="small" style={{ width: '100%' }}>
            <DataToolbar>
              <Select<ReviewBucket>
                style={{ width: 140 }}
                value={bucket}
                options={BUCKET_OPTIONS}
                onChange={setBucket}
              />
              <Select<ReviewStatus | ''>
                style={{ width: 140 }}
                value={status}
                options={STATUS_OPTIONS}
                onChange={setStatus}
              />
              <Input.Search
                allowClear
                placeholder="搜索路径/关键词"
                style={{ width: 260 }}
                onSearch={(value) => {
                  setSearch(value)
                  void loadItems(value)
                }}
              />
            </DataToolbar>
            <Input.TextArea
              rows={3}
              value={rawPath}
              onChange={(event) => setRawPath(event.target.value)}
              placeholder="粘贴本地视频路径"
            />
            <Button
              type="primary"
              icon={<InboxOutlined />}
              loading={submitting}
              onClick={() => void handleCreate()}
            >
              加入待审核
            </Button>
          </Space>
        </Card>

        <div className="review-intake-panels">
          {renderPanel('白名单待审核', 'whitelist', whitelistItems)}
          {renderPanel('黑名单待审核', 'blacklist', blacklistItems)}
        </div>
      </PageScaffold>
    </>
  )
}
