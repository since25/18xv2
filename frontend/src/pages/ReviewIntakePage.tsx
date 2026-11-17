import { useMemo, useState } from 'react'
import {
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CheckOutlined,
  DeleteOutlined,
  EditOutlined,
  InboxOutlined,
  ReloadOutlined,
  StopOutlined,
  UndoOutlined,
} from '@ant-design/icons'

import DataToolbar from '@/layout/DataToolbar'
import PageScaffold from '@/layout/PageScaffold'
import StatusTag from '@/components/StatusTag'
import { statusMeta } from '@/utils/statusText'
import { useApiAction } from '@/hooks/useApiAction'
import { useApiQuery } from '@/hooks/useApiQuery'
import {
  batchApproveReviewIntakeItems,
  batchDeleteReviewIntakeItems,
  batchDismissReviewIntakeItems,
  createIgnoreKeyword,
  createReviewIntakeItem,
  getReviewIntakeSummary,
  listReviewIntakeItems,
  restoreReviewIntakeItem,
  type ReviewBucket,
  type ReviewIntakeBatchResultItem,
  type ReviewIntakeItem,
  type ReviewIntakeSummary,
  type ReviewKeywordCandidate,
  type ReviewStatus,
} from '@/api/reviewIntake'

const BUCKET_OPTIONS: Array<{ label: string; value: ReviewBucket }> = [
  { label: '白名单', value: 'whitelist' },
  { label: '黑名单', value: 'blacklist' },
  { label: '关键词', value: 'keyword' },
]

const STATUS_OPTIONS: Array<{ label: string; value: ReviewStatus | '' }> = [
  { label: '待审核', value: 'pending' },
  { label: '已批准', value: 'approved' },
  { label: '已忽略', value: 'dismissed' },
  { label: '全部', value: '' },
]

// 面板顶部的颜色图例，省得记
const MATCH_LEGEND: Array<{ status: string; label: string }> = [
  { status: 'new', label: '新词' },
  { status: 'similar', label: '有相似词' },
  { status: 'existing', label: '库里已有' },
  { status: 'conflict', label: '冲突' },
  { status: 'ignored', label: '已忽略' },
]

// 只有这两类来源是投稿者自己标出来的名字字段，才允许自动预填；
// 自由文本切片一律留空，避免噪声词被直接批准。
const PREFILL_SOURCES = new Set(['hashtag', 'bracket'])

// 提示组：不是"选它"，而是"这条可以跳过"或"点了会被拒"
const HINT_STATUSES = new Set(['existing', 'conflict'])

// 能加进忽略库的候选状态
const IGNORABLE_STATUSES = ['new', 'similar']

function isHint(candidate: ReviewKeywordCandidate) {
  return HINT_STATUSES.has(candidate.match_status)
}

// 和后端 normalize_keyword_text 保持一致的轻量归一化，用于「×」后本地去重移除
function normalizeWord(word: string) {
  return word
    .normalize('NFKC')
    .replace(/[_\-/]+/g, ' ')
    .replace(/[^\w一-鿿\s·]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
}

// 划词/弹层里拿到的原始文本要去掉首尾空白和标点，避免把「/」「.mp4」这类边角带进关键词
function cleanPickedText(text: string) {
  return text
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^[\p{P}\p{S}]+/u, '')
    .replace(/[\p{P}\p{S}]+$/u, '')
    .trim()
}

// Shift+点击候选词是追加而不是替换；中英文之间补一个空格，中文之间直接连起来
function appendKeyword(current: string, word: string) {
  if (!current) return word
  const needsSpace = /[A-Za-z0-9]$/.test(current) && /^[A-Za-z0-9]/.test(word)
  return needsSpace ? `${current} ${word}` : `${current}${word}`
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
  return bucketLabel(item.bucket)
}

function bucketLabel(bucket: ReviewBucket) {
  if (bucket === 'whitelist') return '白名单'
  if (bucket === 'blacklist') return '黑名单'
  return '关键词'
}

// 三个列表和顶部统计放在同一份数据里，批量操作后可以就地改
interface ReviewItemsData {
  whitelist: ReviewIntakeItem[]
  blacklist: ReviewIntakeItem[]
  keyword: ReviewIntakeItem[]
  summary: ReviewIntakeSummary | null
}

const EMPTY_ITEMS: ReviewItemsData = { whitelist: [], blacklist: [], keyword: [], summary: null }

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

export default function ReviewIntakePage() {
  const [messageApi, contextHolder] = message.useMessage()
  const [modalApi, modalContextHolder] = Modal.useModal()
  const [bucket, setBucket] = useState<ReviewBucket>('whitelist')
  const [rawPath, setRawPath] = useState('')
  const [activeBucket, setActiveBucket] = useState<ReviewBucket>('whitelist')
  const [status, setStatus] = useState<ReviewStatus | ''>('pending')
  const [search, setSearch] = useState('')
  const [keywordDrafts, setKeywordDrafts] = useState<Record<number, string>>({})
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [failures, setFailures] = useState<Record<number, string>>({})
  const [hiddenWords, setHiddenWords] = useState<string[]>([])
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingText, setEditingText] = useState('')
  const [ignorePickerOpen, setIgnorePickerOpen] = useState(false)
  const [ignorePicks, setIgnorePicks] = useState<string[]>([])

  // 出错提示走本页的 messageApi；401 交给全局登录过期处理
  function showError(error: unknown, fallback: string) {
    if ((error as { status?: number } | null)?.status === 401) return
    void messageApi.error(errorMessage(error, fallback))
  }

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

  // 三个列表和顶部统计一起加载；状态筛选或搜索词变化时自动重新加载
  const itemsQuery = useApiQuery(
    () => Promise.all([
      listReviewIntakeItems({ bucket: 'whitelist', status, search: search || undefined, page_size: 200 }),
      listReviewIntakeItems({ bucket: 'blacklist', status, search: search || undefined, page_size: 200 }),
      listReviewIntakeItems({ bucket: 'keyword', status, search: search || undefined, page_size: 200 }),
      getReviewIntakeSummary(),
    ]).then(([white, black, keyword, nextSummary]): ReviewItemsData => {
      setSelectedIds([])
      setFailures({})
      seedDrafts([...white.items, ...black.items, ...keyword.items])
      return {
        whitelist: white.items,
        blacklist: black.items,
        keyword: keyword.items,
        summary: nextSummary,
      }
    }).catch((error: unknown) => {
      showError(error, '加载待审核列表失败')
      throw error
    }),
    [status, search],
    { silent: true, initialData: EMPTY_ITEMS },
  )
  const { loading, reload: loadItems, setData: setItemsData } = itemsQuery
  const whitelistItems = itemsQuery.data.whitelist
  const blacklistItems = itemsQuery.data.blacklist
  const keywordItems = itemsQuery.data.keyword
  const summary = itemsQuery.data.summary

  const stats = useMemo(() => [
    { key: 'white-pending', label: '白待审', value: summary?.whitelist_pending ?? 0 },
    { key: 'black-pending', label: '黑待审', value: summary?.blacklist_pending ?? 0 },
    { key: 'keyword-pending', label: '关键词待审', value: summary?.keyword_pending ?? 0 },
    { key: 'approved', label: '已批准', value: (summary?.whitelist_approved ?? 0) + (summary?.blacklist_approved ?? 0) + (summary?.keyword_approved ?? 0) },
  ], [summary])

  const activeItems = activeBucket === 'whitelist'
    ? whitelistItems
    : activeBucket === 'blacklist' ? blacklistItems : keywordItems

  // 选择状态是全局的，但批量动作只作用在当前 Tab 上，避免误伤另一边
  const activeSelectedIds = useMemo(
    () => activeItems.filter((item) => selectedIds.includes(item.id)).map((item) => item.id),
    [activeItems, selectedIds],
  )

  const readyIds = useMemo(
    () => activeSelectedIds.filter((id) => (keywordDrafts[id] ?? '').trim().length > 0),
    [activeSelectedIds, keywordDrafts],
  )

  // 选中行里所有还能加进忽略库的候选词，去重后给弹层用
  const ignorableWords = useMemo(() => {
    const words = new Set<string>()
    for (const item of activeItems) {
      if (!activeSelectedIds.includes(item.id)) continue
      for (const candidate of item.keyword_candidates) {
        if (!IGNORABLE_STATUSES.includes(candidate.match_status)) continue
        if (hiddenWords.includes(normalizeWord(candidate.keyword))) continue
        words.add(candidate.keyword)
      }
    }
    return [...words]
  }, [activeItems, activeSelectedIds, hiddenWords])

  // 批量成功后只刷新顶部统计，列表靠本地增删，避免整页重拉造成闪烁和跳位
  // 统计刷新失败不影响主流程（静默）
  const summaryAction = useApiAction(getReviewIntakeSummary, {
    silent: true,
    onSuccess: (nextSummary) => setItemsData((prev = EMPTY_ITEMS) => ({ ...prev, summary: nextSummary })),
  })

  function refreshSummary() {
    return summaryAction.run()
  }

  // 搜索词没变时也要重新加载（与原来点搜索即重拉一致）
  function handleSearch(value: string) {
    if (value === search) {
      void loadItems()
      return
    }
    setSearch(value)
  }

  // 投递成功后等列表刷新完再结束按钮加载态
  const createAction = useApiAction(createReviewIntakeItem, {
    silent: true,
    onSuccess: async (item) => {
      void messageApi.success(`已加入${itemLabel(item)}待审`)
      setRawPath('')
      await loadItems()
    },
  })
  const submitting = createAction.loading

  async function handleCreate() {
    if (!rawPath.trim()) {
      void messageApi.warning('请先粘贴路径')
      return
    }
    const result = await createAction.run({
      bucket,
      raw_path: rawPath,
      source: 'manual_web',
    })
    if (!result.ok) showError(result.error, '投递失败')
  }

  // 填词和勾选是同一个动作：有词就自动勾上，清空就自动取消
  function setDraft(itemId: number, keyword: string) {
    setKeywordDrafts((current) => ({ ...current, [itemId]: keyword }))
    setSelectedIds((current) => {
      const has = current.includes(itemId)
      if (keyword.trim()) return has ? current : [...current, itemId]
      return has ? current.filter((id) => id !== itemId) : current
    })
    setFailures((current) => {
      if (current[itemId] === undefined) return current
      const next = { ...current }
      delete next[itemId]
      return next
    })
  }

  function pickCandidate(itemId: number, keyword: string, append: boolean) {
    const current = keywordDrafts[itemId] ?? ''
    setDraft(itemId, append ? appendKeyword(current, keyword) : keyword)
  }

  // 在路径上划词/双击选词后直接填进关键词框，省掉复制粘贴
  function handlePathSelection(itemId: number) {
    const picked = cleanPickedText(window.getSelection?.()?.toString() ?? '')
    if (!picked) return
    setDraft(itemId, picked)
  }

  function openEditor(item: ReviewIntakeItem) {
    setEditingId(item.id)
    setEditingText((keywordDrafts[item.id] ?? '').trim() || item.raw_path)
  }

  function confirmEditor() {
    if (editingId === null) return
    const picked = cleanPickedText(editingText)
    if (!picked) {
      void messageApi.warning('关键词不能为空')
      return
    }
    setDraft(editingId, picked)
    setEditingId(null)
  }

  // 单个加词出错由调用方决定怎么提示（单个弹错误，批量只计数）
  const ignoreWordAction = useApiAction(createIgnoreKeyword, { silent: true })

  async function handleIgnoreWord(word: string) {
    const result = await ignoreWordAction.run(word)
    if (!result.ok) {
      showError(result.error, '加入忽略库失败')
      return
    }
    // 候选的状态色是投递那一刻算好存下来的，重新拉列表不会让它变灰，
    // 所以这里直接在本地把所有同名标签隐藏掉。
    setHiddenWords((current) => [...current, normalizeWord(word)])
    void messageApi.success(`已把「${word}」加入忽略库`)
  }

  // 批量加入忽略库：逐个提交，失败的只计数，结束后统一提示
  const batchIgnoreAction = useApiAction(async (words: string[]) => {
    let failed = 0
    for (const word of words) {
      const result = await ignoreWordAction.run(word)
      if (result.ok) {
        setHiddenWords((current) => [...current, normalizeWord(word)])
      } else {
        failed += 1
      }
    }
    return failed
  }, { silent: true })

  async function handleBatchIgnoreWords() {
    if (!ignorePicks.length) {
      void messageApi.warning('请先选择要忽略的词')
      return
    }
    const result = await batchIgnoreAction.run(ignorePicks)
    const failed = result.ok ? result.data : 0
    setIgnorePickerOpen(false)
    setIgnorePicks([])
    if (failed) {
      void messageApi.warning(`已忽略 ${ignorePicks.length - failed} 个词，${failed} 个失败`)
    } else {
      void messageApi.success(`已把 ${ignorePicks.length} 个词加入忽略库`)
    }
  }

  function statusMatchesFilter(itemStatus: ReviewStatus) {
    return status === '' || status === itemStatus
  }

  // 成功的行按当前筛选决定是就地更新还是移出列表，失败的行留在原地并记下原因
  function applyBatchResults(results: ReviewIntakeBatchResultItem[], removeAlways = false) {
    const removeIds = new Set<number>()
    const replacements = new Map<number, ReviewIntakeItem>()
    const nextFailures: Record<number, string> = {}

    for (const result of results) {
      if (!result.ok) {
        nextFailures[result.id] = result.error ?? '处理失败'
        continue
      }
      if (removeAlways || result.item === null || !statusMatchesFilter(result.item.status)) {
        removeIds.add(result.id)
      } else {
        replacements.set(result.id, result.item)
      }
    }

    const apply = (items: ReviewIntakeItem[]) =>
      items
        .filter((item) => !removeIds.has(item.id))
        .map((item) => replacements.get(item.id) ?? item)

    setItemsData((prev = EMPTY_ITEMS) => ({ ...prev, whitelist: apply(prev.whitelist), blacklist: apply(prev.blacklist) }))
    setSelectedIds((current) =>
      current.filter((id) => !removeIds.has(id) && !replacements.has(id)),
    )
    setFailures((current) => {
      const next = { ...current }
      for (const result of results) {
        if (result.ok) delete next[result.id]
      }
      return { ...next, ...nextFailures }
    })
    void refreshSummary()
  }

  function reportBatch(succeeded: number, failed: number, verb: string) {
    if (failed === 0) {
      void messageApi.success(`已${verb} ${succeeded} 条`)
    } else {
      void messageApi.warning(`${verb}成功 ${succeeded} 条，失败 ${failed} 条，失败原因见列表`)
    }
  }

  // 批量操作的出错提示文字各不相同，统一设为 silent 后自行提示
  const approveAction = useApiAction(batchApproveReviewIntakeItems, { silent: true })
  const dismissAction = useApiAction(batchDismissReviewIntakeItems, { silent: true })
  const deleteAction = useApiAction(batchDeleteReviewIntakeItems, { silent: true })
  const batching = approveAction.loading || dismissAction.loading || deleteAction.loading
    || batchIgnoreAction.loading

  async function runBatchApprove(entries: Array<{ id: number; keyword: string }>) {
    const result = await approveAction.run(entries)
    if (!result.ok) {
      showError(result.error, '批准失败')
      return
    }
    applyBatchResults(result.data.results)
    reportBatch(result.data.succeeded, result.data.failed, '批准')
  }

  async function runBatchDismiss(ids: number[]) {
    const result = await dismissAction.run(ids)
    if (!result.ok) {
      showError(result.error, '忽略失败')
      return
    }
    applyBatchResults(result.data.results)
    reportBatch(result.data.succeeded, result.data.failed, '忽略')
  }

  async function runBatchDelete(ids: number[]) {
    const result = await deleteAction.run(ids)
    if (!result.ok) {
      showError(result.error, '删除失败')
      return
    }
    applyBatchResults(result.data.results, true)
    reportBatch(result.data.succeeded, result.data.failed, '删除')
  }

  async function handleApprove(item: ReviewIntakeItem) {
    const keyword = (keywordDrafts[item.id] ?? '').trim()
    if (!keyword) {
      void messageApi.warning('请先确认关键词')
      return
    }
    await runBatchApprove([{ id: item.id, keyword }])
  }

  const restoreAction = useApiAction(restoreReviewIntakeItem, { silent: true })

  async function handleRestore(item: ReviewIntakeItem) {
    const result = await restoreAction.run(item.id)
    if (!result.ok) {
      showError(result.error, '恢复失败')
      return
    }
    applyBatchResults([{ id: item.id, ok: true, item: result.data, error: null }])
    void messageApi.success('已恢复为待审核')
  }

  function handleBatchApprove() {
    const entries = readyIds.map((id) => ({ id, keyword: (keywordDrafts[id] ?? '').trim() }))
    if (!entries.length) {
      void messageApi.warning('选中的行里没有填好关键词的')
      return
    }
    const skipped = activeSelectedIds.length - entries.length
    void modalApi.confirm({
      title: `批准 ${entries.length} 条，写入${bucketLabel(activeBucket)}`,
      width: 520,
      content: (
        <div className="review-confirm-list">
          {skipped > 0 ? <p>另有 {skipped} 条没填关键词，将被跳过。</p> : null}
          <div className="review-confirm-words">
            {entries.map((entry) => (
              <Tag key={entry.id}>{entry.keyword}</Tag>
            ))}
          </div>
        </div>
      ),
      okText: '确认批准',
      cancelText: '再看看',
      onOk: () => runBatchApprove(entries),
    })
  }

  function handleBatchDelete() {
    void modalApi.confirm({
      title: `删除 ${activeSelectedIds.length} 条待审核记录？`,
      content: '删除后不可恢复。只是想清理的话建议用「批量忽略」。',
      okText: '确认删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => runBatchDelete(activeSelectedIds),
    })
  }

  function openIgnorePicker() {
    if (!ignorableWords.length) {
      void messageApi.warning('选中的行里没有可忽略的候选词')
      return
    }
    setIgnorePicks([])
    setIgnorePickerOpen(true)
  }

  const columns: ColumnsType<ReviewIntakeItem> = [
    {
      title: '候选（点选填入，Shift+点击追加）',
      dataIndex: 'keyword_candidates',
      render: (_: unknown, item) => {
        const usable = item.keyword_candidates.filter(
          (candidate) => !hiddenWords.includes(normalizeWord(candidate.keyword)),
        )
        const hints = usable.filter(isHint)
        const picks = usable.filter((candidate) => !isHint(candidate))

        const renderTag = (candidate: ReviewKeywordCandidate, index: number) => {
          const canIgnore = IGNORABLE_STATUSES.includes(candidate.match_status)
          const meta = statusMeta('keyword', candidate.match_status)
          return (
            <span
              key={`${candidate.keyword}-${candidate.match_status}-${index}`}
              className={`status-tag status-tag--${meta.tone} review-candidate-tag review-candidate-tag--pickable`}
              title={meta.label}
              onClick={(event) => pickCandidate(item.id, candidate.keyword, event.shiftKey)}
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
            </span>
          )
        }

        if (!usable.length) {
          return <Tag className="review-candidate-tag" color="default">未提取，请在下方路径上划词</Tag>
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
              {picks.map(renderTag)}
            </Space>
          </div>
        )
      },
    },
    {
      title: '确认关键词',
      key: 'keyword',
      width: 250,
      render: (_: unknown, item) => (
        <Space.Compact className="review-keyword-cell">
          <Input
            size="small"
            value={keywordDrafts[item.id] ?? ''}
            onChange={(event) => setDraft(item.id, event.target.value)}
            placeholder={`${bucketLabel(item.bucket)}词`}
          />
          <Tooltip title="从完整路径里编辑">
            <Button
              aria-label={`编辑关键词 ${item.id}`}
              size="small"
              icon={<EditOutlined />}
              onClick={() => openEditor(item)}
            />
          </Tooltip>
        </Space.Compact>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (value: ReviewStatus) => {
        return <StatusTag domain="review" value={value} />
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
            <Popconfirm title="忽略这条待审核项？" onConfirm={() => void runBatchDismiss([item.id])}>
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
          <Popconfirm title="删除这条记录？" onConfirm={() => void runBatchDelete([item.id])}>
            <Tooltip title="删除">
              <Button aria-label="删除" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  function renderPathRow(item: ReviewIntakeItem) {
    return (
      <div className="review-path-row">
        <span className="review-path-label">路径</span>
        <span
          className="review-path-text"
          data-testid={`review-path-${item.id}`}
          onMouseUp={() => handlePathSelection(item.id)}
          title="拖选或双击可直接填入关键词"
        >
          {item.raw_path}
        </span>
        {failures[item.id] ? (
          <span className="review-path-error">失败原因：{failures[item.id]}</span>
        ) : null}
      </div>
    )
  }

  function renderTable(items: ReviewIntakeItem[]) {
    if (!items.length) return <Empty description="没有待处理记录" />
    return (
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        pagination={false}
        columns={columns}
        dataSource={items}
        scroll={{ x: 760 }}
        rowClassName={(item) => {
          if (failures[item.id]) return 'review-row--failed'
          return selectedIds.includes(item.id) ? 'review-row--ready' : ''
        }}
        rowSelection={{
          selectedRowKeys: selectedIds,
          onChange: (keys) => setSelectedIds(keys as number[]),
          columnWidth: 40,
        }}
        expandable={{
          showExpandColumn: false,
          expandedRowKeys: items.map((item) => item.id),
          expandedRowRender: renderPathRow,
        }}
      />
    )
  }

  const tabItems = [
    {
      key: 'whitelist',
      label: `白名单待审 ${whitelistItems.length}`,
      children: renderTable(whitelistItems),
    },
    {
      key: 'blacklist',
      label: `黑名单待审 ${blacklistItems.length}`,
      children: renderTable(blacklistItems),
    },
    {
      key: 'keyword',
      label: `关键词待审 ${keywordItems.length}`,
      children: renderTable(keywordItems),
    },
  ]

  return (
    <>
      {contextHolder}
      {modalContextHolder}
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
                onSearch={handleSearch}
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

        <Card className="soft-card review-intake-card">
          <div className="review-legend">
            {MATCH_LEGEND.map((entry) => (
              <StatusTag key={entry.status} domain="keyword" value={entry.status} />
            ))}
          </div>
          <Tabs
            activeKey={activeBucket}
            onChange={(key) => setActiveBucket(key as ReviewBucket)}
            items={tabItems}
          />
        </Card>
      </PageScaffold>

      {activeSelectedIds.length ? (
        <div className="review-batch-bar" role="toolbar" aria-label="批量操作">
          <span className="review-batch-count">
            已选 {activeSelectedIds.length} 条 · 其中 {readyIds.length} 条已填关键词
          </span>
          <Space size={8} wrap>
            <Button type="primary" loading={batching} onClick={handleBatchApprove}>
              批量批准
            </Button>
            <Button loading={batching} onClick={() => void runBatchDismiss(activeSelectedIds)}>
              批量忽略
            </Button>
            <Button loading={batching} onClick={openIgnorePicker}>
              批量加入忽略库
            </Button>
            <Button danger loading={batching} onClick={handleBatchDelete}>
              批量删除
            </Button>
            <Button type="text" onClick={() => setSelectedIds([])}>
              清空选择
            </Button>
          </Space>
        </div>
      ) : null}

      <Modal
        open={editingId !== null}
        title="编辑关键词"
        okText="确认"
        cancelText="取消"
        onOk={confirmEditor}
        onCancel={() => setEditingId(null)}
      >
        <p className="review-editor-hint">删掉不需要的部分，剩下的就是关键词。</p>
        <Input.TextArea
          rows={4}
          value={editingText}
          onChange={(event) => setEditingText(event.target.value)}
        />
      </Modal>

      <Modal
        open={ignorePickerOpen}
        title="选择要加入忽略库的词"
        okText="加入忽略库"
        cancelText="取消"
        confirmLoading={batching}
        onOk={() => void handleBatchIgnoreWords()}
        onCancel={() => setIgnorePickerOpen(false)}
      >
        <p className="review-editor-hint">勾选的词以后不再作为候选出现。</p>
        <Checkbox.Group
          className="review-ignore-picker"
          value={ignorePicks}
          options={ignorableWords.map((word) => ({ label: word, value: word }))}
          onChange={(values) => setIgnorePicks(values as string[])}
        />
      </Modal>
    </>
  )
}
