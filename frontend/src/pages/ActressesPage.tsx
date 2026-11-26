import { useRef, useState } from 'react'
import { ReloadOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Avatar, Button, Drawer, Input, Popconfirm, Select, Space, Spin, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  actressImageUrl,
  addActressAlias,
  getActress,
  listActresses,
  mergeActress,
  refreshActressAvatars,
  removeActressAlias,
  setActressStatus,
  type ActressAliasItem,
  type ActressAvatarState,
  type ActressDetail,
  type ActressFilmActor,
  type ActressFilmItem,
  type ActressListResponse,
  type ActressMarkItem,
  type ActressSort,
  type ActressStatus,
  type ActressStatusResponse,
  type ActressSummary,
} from '@/api/actresses'
import TimeText from '@/components/TimeText'
import { useApiAction } from '@/hooks/useApiAction'
import { useApiQuery } from '@/hooks/useApiQuery'
import DataToolbar from '@/layout/DataToolbar'
import PageScaffold from '@/layout/PageScaffold'
import SurfacePanel from '@/layout/SurfacePanel'

const { Text, Title } = Typography
const PAGE_SIZE = 50
const FILM_PAGE_SIZE = 20

const STATUS_LABELS: Record<ActressStatus, string> = { none: '未标', blacklist: '黑名单', whitelist: '白名单' }
// 对应 index.css 里 status-tag 的色调
const STATUS_TONES: Record<ActressStatus, string> = { none: 'neutral', blacklist: 'danger', whitelist: 'success' }
// 行内和批量操作：目标状态与按钮文字
const STATUS_ACTIONS: Array<{ status: ActressStatus; label: string }> = [
  { status: 'blacklist', label: '拉黑' },
  { status: 'whitelist', label: '加白' },
  { status: 'none', label: '设为未标' },
]
const AVATAR_STATE_LABELS: Record<ActressAvatarState, string> = {
  pending: '待处理',
  uploaded: '已上传',
  present: '本来就有',
  not_found: 'Gfriends 里找不到',
  no_person: 'Jellyfin 里没有这个人物',
  error: '失败',
}
const MARK_SOURCE_LABELS: Record<string, string> = { web: '网页', player: '播放器', import: '导入', merge: '合并' }
const STATUS_FILTER_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'none', label: '未标' },
  { value: 'blacklist', label: '黑名单' },
  { value: 'whitelist', label: '白名单' },
]
const SORT_OPTIONS = [
  { value: 'film_count', label: '按片数' },
  { value: 'name', label: '按名字' },
]
const EMPTY_LIST: ActressListResponse = { items: [], total: 0, counts: { none: 0, blacklist: 0, whitelist: 0 } }

function StatusLabel({ status }: { status: ActressStatus }) {
  return <span className={`status-tag status-tag--${STATUS_TONES[status]}`}>{STATUS_LABELS[status]}</span>
}

/** 改状态后的提示：删除草稿增减了几部 */
function statusChangeText(res: ActressStatusResponse) {
  const parts: string[] = []
  if (res.candidates_added) parts.push(`已放进删除草稿 ${res.candidates_added} 部`)
  if (res.candidates_removed) parts.push(`草稿移出 ${res.candidates_removed} 部`)
  if (parts.length) return parts.join('，')
  return res.changed ? `已改 ${res.changed} 人，删除草稿没有变化` : '状态没有变化'
}

/** 头像：转发的 Jellyfin 人物图；取不到（404 或加载失败）时显示占位 */
function ActressAvatar({ id, name }: { id: number; name: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <span role="img" aria-label={`${name} 没有头像`}>
        <Avatar shape="square" size={40} icon={<UserOutlined />} />
      </span>
    )
  }
  return (
    <img
      src={actressImageUrl(id)}
      alt={name}
      width={40}
      height={40}
      loading="lazy"
      onError={() => setFailed(true)}
      style={{ display: 'block', objectFit: 'cover', borderRadius: 4 }}
    />
  )
}

/** 合并到另一位：按名字搜目标，确认后合并，返回合并后的目标详情 */
function MergeSection({ actress, onMerged }: { actress: ActressDetail; onMerged: (target: ActressDetail) => void }) {
  const [options, setOptions] = useState<ActressSummary[]>([])
  // 选中时记下目标本身：之后再搜别的名字，选项里没有她了，确认框仍显示她
  const [target, setTarget] = useState<ActressSummary | undefined>(undefined)
  // 只采用最后一次搜索的结果
  const searchSeq = useRef(0)

  const search = async (text: string) => {
    const seq = ++searchSeq.current
    const q = text.trim()
    if (!q) {
      setOptions([])
      return
    }
    try {
      const res = await listActresses({ q, sort: 'film_count', page_size: 20 })
      if (seq === searchSeq.current) setOptions(res.items.filter((item) => item.id !== actress.id))
    } catch {
      if (seq === searchSeq.current) setOptions([])
    }
  }

  const mergeAction = useApiAction((intoId: number) => mergeActress(actress.id, intoId), {
    successMessage: (data) => `已合并进 ${data.canonical_name}`,
    onSuccess: (data) => onMerged(data),
  })

  return (
    <Space wrap>
      <Select<number>
        aria-label="合并目标"
        style={{ width: 280 }}
        placeholder="搜索要合并进的女优"
        showSearch={{ filterOption: false, onSearch: (value) => void search(value) }}
        value={target?.id}
        onChange={(id) => setTarget(options.find((item) => item.id === id))}
        notFoundContent="输入名字搜索"
        // 选中的目标不在当前搜索结果里时也要有选项，选择框才显示她的名字
        options={(target && !options.some((item) => item.id === target.id) ? [target, ...options] : options).map(
          (item) => ({
            value: item.id,
            label: `${item.canonical_name}（${STATUS_LABELS[item.status]}，${item.film_count} 部）`,
          }),
        )}
      />
      <Popconfirm
        title={`把「${actress.canonical_name}」合并进「${target?.canonical_name ?? ''}」？`}
        description="她的名字和别名会变成对方的别名，标记记录一并转过去；对方是未标时，会继承她的黑名单/白名单状态。"
        disabled={!target}
        onConfirm={() => {
          if (target) void mergeAction.run(target.id)
        }}
      >
        <Button disabled={!target} loading={mergeAction.loading}>
          合并
        </Button>
      </Popconfirm>
    </Space>
  )
}

/** 详情抽屉内容：别名、合并、标记记录、她的片子 */
function ActressDetailBody({
  actressId,
  onChanged,
  onMerged,
}: {
  actressId: number
  onChanged: () => void
  onMerged: (target: ActressDetail) => void
}) {
  const { data: detail, error, setData } = useApiQuery(() => getActress(actressId), [actressId], { silent: true })
  const [aliasInput, setAliasInput] = useState('')

  const aliasAction = useApiAction((alias: string) => addActressAlias(actressId, alias), {
    successMessage: (_data, alias) => `已添加别名 ${alias}`,
    onSuccess: (data) => {
      setData(data)
      setAliasInput('')
      onChanged()
    },
  })
  const avatarAction = useApiAction(() => refreshActressAvatars({ actress_ids: [actressId] }), {
    successMessage: '已开始重新找头像，稍后刷新查看',
  })
  const removeAliasAction = useApiAction((item: ActressAliasItem) => removeActressAlias(actressId, item.id), {
    successMessage: (_data, item) => `已删除别名 ${item.alias}`,
    onSuccess: (data) => {
      // 用接口返回的新详情刷新抽屉
      setData(data)
      onChanged()
    },
  })

  if (error) return <Alert type="error" showIcon title={`详情加载失败：${error.message}`} />
  if (!detail) return <Spin />

  const submitAlias = () => {
    const alias = aliasInput.trim()
    if (alias) void aliasAction.run(alias)
  }

  const markColumns: ColumnsType<ActressMarkItem> = [
    { title: '时间', dataIndex: 'created_at', width: 170, render: (value: string) => <TimeText value={value} /> },
    {
      title: '变化',
      key: 'change',
      render: (_value, mark) => `${STATUS_LABELS[mark.from_status]} → ${STATUS_LABELS[mark.to_status]}`,
    },
    { title: '来源', dataIndex: 'source', width: 80, render: (value: string) => MARK_SOURCE_LABELS[value] ?? value },
    { title: '备注', dataIndex: 'note', render: (value: string | null) => value ?? '-' },
  ]
  const filmColumns: ColumnsType<ActressFilmItem> = [
    { title: '番号', dataIndex: 'number', width: 120 },
    { title: '标题', dataIndex: 'title', render: (value: string | null) => value ?? '-' },
    {
      title: '同片演员',
      dataIndex: 'actors',
      render: (actors: ActressFilmActor[]) =>
        actors.map((actor) => `${actor.name}（${STATUS_LABELS[actor.status]}）`).join('、'),
    },
    { title: '保护', dataIndex: 'protected', width: 80, render: (value: boolean) => (value ? '受保护' : '-') },
    { title: '草稿', dataIndex: 'in_candidates', width: 90, render: (value: boolean) => (value ? '在草稿中' : '-') },
  ]

  return (
    <>
      <Space size={12} wrap style={{ marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          {detail.canonical_name}
        </Title>
        <StatusLabel status={detail.status} />
        <Text type="secondary">{`${detail.film_count} 部`}</Text>
        {detail.candidate_count > 0 && <Text type="danger">{`草稿中 ${detail.candidate_count} 部`}</Text>}
      </Space>

      <Space size={12} wrap style={{ marginBottom: 20 }}>
        <Text type="secondary">
          {`头像：${AVATAR_STATE_LABELS[detail.avatar_state]}${detail.avatar_note ? `（${detail.avatar_note}）` : ''}`}
        </Text>
        <Button size="small" loading={avatarAction.loading} onClick={() => void avatarAction.run()}>
          重新找头像
        </Button>
      </Space>

      <Title level={5}>别名</Title>
      <div style={{ marginBottom: 8 }}>
        {detail.alias_items.length ? (
          <Space wrap size={[12, 4]}>
            {detail.alias_items.map((item) => (
              <span key={item.id}>
                <Tag>{item.alias}</Tag>
                <Button
                  type="link"
                  size="small"
                  aria-label={`删除别名 ${item.alias}`}
                  disabled={removeAliasAction.loading}
                  onClick={() => void removeAliasAction.run(item)}
                >
                  删除
                </Button>
              </span>
            ))}
          </Space>
        ) : (
          <Text type="secondary">没有别名</Text>
        )}
      </div>
      <Space.Compact style={{ width: 320, marginBottom: 20 }}>
        <Input
          aria-label="新别名"
          placeholder="新别名"
          value={aliasInput}
          onChange={(event) => setAliasInput(event.target.value)}
          onPressEnter={submitAlias}
        />
        <Button onClick={submitAlias} loading={aliasAction.loading} disabled={!aliasInput.trim()}>
          添加
        </Button>
      </Space.Compact>

      <Title level={5}>合并到另一位</Title>
      <div style={{ marginBottom: 20 }}>
        <MergeSection actress={detail} onMerged={onMerged} />
      </div>

      <Title level={5}>标记记录</Title>
      <Table<ActressMarkItem>
        rowKey={(mark) => `${mark.created_at}-${mark.from_status}-${mark.to_status}-${mark.source}`}
        size="small"
        columns={markColumns}
        dataSource={detail.marks}
        pagination={false}
        locale={{ emptyText: '没有标记记录' }}
        style={{ marginBottom: 20 }}
      />

      <Title level={5}>她的片子</Title>
      <Table<ActressFilmItem>
        rowKey="film_dir"
        size="small"
        columns={filmColumns}
        dataSource={detail.films}
        pagination={detail.films.length > FILM_PAGE_SIZE ? { pageSize: FILM_PAGE_SIZE, showSizeChanger: false } : false}
        locale={{ emptyText: '没有片子' }}
      />
    </>
  )
}

export default function ActressesPage() {
  const [statusFilter, setStatusFilter] = useState<ActressStatus | 'all'>('all')
  const [keyword, setKeyword] = useState('')
  const [sort, setSort] = useState<ActressSort>('film_count')
  const [page, setPage] = useState(1)
  // 改动成功后递增，触发列表重新加载
  const [reloadToken, setReloadToken] = useState(0)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  // 抽屉关闭时保留 detailId，关闭动画期间内容不闪空
  const [detailId, setDetailId] = useState<number | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const { data: list, loading } = useApiQuery(
    () =>
      listActresses({
        status: statusFilter === 'all' ? undefined : statusFilter,
        q: keyword || undefined,
        sort,
        page,
        page_size: PAGE_SIZE,
      }),
    [statusFilter, keyword, sort, page, reloadToken],
    { initialData: EMPTY_LIST },
  )
  const reloadList = () => setReloadToken((token) => token + 1)

  const statusAction = useApiAction(
    (ids: number[], status: ActressStatus) => setActressStatus({ actress_ids: ids, status, source: 'web' }),
    { successMessage: statusChangeText, onSuccess: reloadList },
  )

  const changeSelected = async (status: ActressStatus) => {
    const result = await statusAction.run(selectedIds, status)
    if (result.ok) setSelectedIds([])
  }

  const openDetail = (id: number) => {
    setDetailId(id)
    setDrawerOpen(true)
  }

  const columns: ColumnsType<ActressSummary> = [
    {
      title: '头像',
      key: 'avatar',
      width: 64,
      render: (_value, row) => <ActressAvatar id={row.id} name={row.canonical_name} />,
    },
    {
      title: '名字',
      key: 'name',
      render: (_value, row) => (
        <>
          <div>
            <Text strong>{row.canonical_name}</Text>
          </div>
          {row.aliases.length > 0 && <Text type="secondary">{`别名：${row.aliases.join('、')}`}</Text>}
        </>
      ),
    },
    { title: '状态', dataIndex: 'status', width: 90, render: (value: ActressStatus) => <StatusLabel status={value} /> },
    { title: '片数', dataIndex: 'film_count', width: 90, render: (value: number) => `${value} 部` },
    {
      title: '待删',
      dataIndex: 'candidate_count',
      width: 110,
      render: (value: number) => (value > 0 ? `草稿中 ${value} 部` : '-'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 210,
      render: (_value, row) => (
        <Space size={4}>
          {STATUS_ACTIONS.filter((action) => action.status !== row.status).map((action) => (
            <Button
              key={action.status}
              size="small"
              danger={action.status === 'blacklist'}
              disabled={statusAction.loading}
              onClick={(event) => {
                // 不触发整行点击（打开详情）
                event.stopPropagation()
                void statusAction.run([row.id], action.status)
              }}
            >
              {action.label}
            </Button>
          ))}
        </Space>
      ),
    },
  ]

  const avatarsAction = useApiAction(() => refreshActressAvatars(), {
    successMessage: '已开始补头像，稍后刷新查看',
  })

  const stats = [
    { key: 'blacklist', label: '黑名单', value: list.counts.blacklist },
    { key: 'whitelist', label: '白名单', value: list.counts.whitelist },
    { key: 'none', label: '未标', value: list.counts.none },
  ]

  return (
    <PageScaffold
      title="女优"
      description="按 NFO 里的演员建档。拉黑后她的片子进入删除草稿，要在「女优删除」页确认后才会删除；白名单女优的片子不会进草稿。"
      stats={stats}
      actions={
        <Space>
          <Button loading={avatarsAction.loading} onClick={() => void avatarsAction.run()}>
            补头像
          </Button>
          <Button icon={<ReloadOutlined />} onClick={reloadList}>
            刷新
          </Button>
        </Space>
      }
    >
      <SurfacePanel>
        <div style={{ marginBottom: 12 }}>
          <DataToolbar
            left={
              <>
                <Input.Search
                  aria-label="搜索名字"
                  allowClear
                  placeholder="搜索名字或别名"
                  style={{ width: 220 }}
                  onSearch={(value) => {
                    setKeyword(value.trim())
                    setPage(1)
                  }}
                />
                <Select<ActressStatus | 'all'>
                  aria-label="状态筛选"
                  style={{ width: 120 }}
                  value={statusFilter}
                  options={STATUS_FILTER_OPTIONS}
                  onChange={(value) => {
                    setStatusFilter(value)
                    setPage(1)
                  }}
                />
                <Select<ActressSort>
                  aria-label="排序"
                  style={{ width: 120 }}
                  value={sort}
                  options={SORT_OPTIONS}
                  onChange={(value) => {
                    setSort(value)
                    setPage(1)
                  }}
                />
              </>
            }
            right={
              selectedIds.length > 0 ? (
                <>
                  <Text>{`已选 ${selectedIds.length} 位`}</Text>
                  {STATUS_ACTIONS.map((action) => (
                    <Button
                      key={action.status}
                      size="small"
                      danger={action.status === 'blacklist'}
                      loading={statusAction.loading}
                      onClick={() => void changeSelected(action.status)}
                    >
                      {`批量${action.label}`}
                    </Button>
                  ))}
                  <Button size="small" onClick={() => setSelectedIds([])}>
                    取消选择
                  </Button>
                </>
              ) : null
            }
          />
        </div>
        <Table<ActressSummary>
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={list.items}
          rowSelection={{
            selectedRowKeys: selectedIds,
            onChange: (keys) => setSelectedIds(keys as number[]),
            preserveSelectedRowKeys: true,
            columnWidth: 40,
          }}
          onRow={(row) => ({
            onClick: () => openDetail(row.id),
            onKeyDown: (event) => {
              // 只响应行本身获得焦点时的回车，行内按钮的回车不打开详情
              if (event.key === 'Enter' && event.target === event.currentTarget) openDetail(row.id)
            },
            tabIndex: 0,
            style: { cursor: 'pointer' },
          })}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total: list.total,
            showSizeChanger: false,
            onChange: setPage,
          }}
          locale={{ emptyText: '没有女优' }}
        />
      </SurfacePanel>

      <Drawer title="女优详情" size={760} open={drawerOpen} onClose={() => setDrawerOpen(false)} destroyOnHidden>
        {detailId !== null && (
          <ActressDetailBody
            key={detailId}
            actressId={detailId}
            onChanged={reloadList}
            onMerged={(target) => {
              setDetailId(target.id)
              reloadList()
            }}
          />
        )}
      </Drawer>
    </PageScaffold>
  )
}
