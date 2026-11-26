import { useEffect, useRef, useState } from 'react'
import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Checkbox, Modal, Space, Table, Tabs, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  checkCandidatesRemote,
  createDeleteBatch,
  getDeleteBatch,
  keepCandidates,
  listCandidates,
  listDeleteBatches,
  listKept,
  removeKept,
  resumeDeleteBatch,
  selectCandidates,
  type ActressCandidateItem,
  type ActressCandidateListResponse,
  type ActressDeleteBatchDetail,
  type ActressDeleteBatchFileItem,
  type ActressDeleteBatchFilmItem,
  type ActressDeleteBatchListResponse,
  type ActressDeleteBatchSummary,
  type ActressFilmActor,
  type ActressKeptItem,
  type ActressKeptListResponse,
} from '@/api/actresses'
import TimeText from '@/components/TimeText'
import { useApiAction } from '@/hooks/useApiAction'
import { useApiQuery } from '@/hooks/useApiQuery'
import DataToolbar from '@/layout/DataToolbar'
import PageScaffold from '@/layout/PageScaffold'
import SurfacePanel from '@/layout/SurfacePanel'

const { Text, Title } = Typography

type TabKey = 'candidates' | 'batches' | 'kept'
type BatchStatus = ActressDeleteBatchSummary['status']
type FilmStatus = ActressDeleteBatchFilmItem['status']
type FileStatus = ActressDeleteBatchFileItem['status']
type FileGroup = ActressDeleteBatchFileItem['group']
type RemoteState = ActressCandidateItem['remote_state']
type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

/** 当前打开的批次；token 每次打开递增，用作 key 让详情重新挂载、重新开始轮询 */
interface OpenBatch {
  id: number
  token: number
  // 续跑时记下续跑前的完成时间：服务端还是这个值，说明续跑的这一轮还没结束
  waitFinishedAt?: string | null
}

const POLL_MS = 3000
// 后端检查 115 一次最多 50 部
const CHECK_CHUNK = 50
// 刚建好的批次是 pending，后台开始执行后变成 running；这两种都要继续轮询
const ACTIVE_BATCH_STATUSES: BatchStatus[] = ['pending', 'running']
const RESUMABLE_BATCH_STATUSES: BatchStatus[] = ['failed', 'interrupted']

const BATCH_STATUS: Record<BatchStatus, [string, Tone]> = {
  pending: ['待执行', 'neutral'],
  running: ['执行中', 'info'],
  completed: ['已完成', 'success'],
  failed: ['有失败', 'danger'],
  interrupted: ['已中断', 'warning'],
}
const FILM_STATUS: Record<FilmStatus, [string, Tone]> = {
  pending: ['待执行', 'neutral'],
  deleted: ['已删除', 'success'],
  skipped: ['已跳过', 'warning'],
  failed: ['失败', 'danger'],
}
const FILE_STATUS: Record<FileStatus, [string, Tone]> = {
  pending: ['待执行', 'neutral'],
  deleted: ['已删除', 'success'],
  missing: ['已不存在', 'neutral'],
  failed: ['失败', 'danger'],
}
const FILE_GROUP_LABELS: Record<FileGroup, string> = {
  remote_115: '115 原文件',
  source_strm: 'porn_tv1 STRM',
  organized_dir: '302porn_tv1 目录',
}
const REMOTE_STATE: Record<RemoteState, [string, Tone]> = {
  unchecked: ['未检查', 'neutral'],
  found: ['可解析', 'success'],
  missing: ['已不存在', 'warning'],
  error: ['有问题', 'danger'],
}
const JELLYFIN_REFRESH_LABELS: Record<string, string> = { done: '已触发扫库', skipped: '未扫库', error: '扫库失败' }
const ACTOR_STATUS_LABELS: Record<ActressFilmActor['status'], string> = {
  none: '未标',
  blacklist: '黑名单',
  whitelist: '白名单',
}

const EMPTY_CANDIDATES: ActressCandidateListResponse = { items: [], total: 0, selected: 0 }
const EMPTY_BATCHES: ActressDeleteBatchListResponse = { items: [] }
const EMPTY_KEPT: ActressKeptListResponse = { items: [] }

function ToneLabel({ entry }: { entry: [string, Tone] }) {
  return <span className={`status-tag status-tag--${entry[1]}`}>{entry[0]}</span>
}

function errorStatus(error: Error) {
  return (error as Error & { status?: number }).status
}

// ---------- 待删清单 ----------

function CandidatesTab({ onBatchCreated }: { onBatchCreated: (batchId: number) => void }) {
  const [modal, modalHolder] = Modal.useModal()
  const { data, loading, reload, setData } = useApiQuery(() => listCandidates(), [], {
    initialData: EMPTY_CANDIDATES,
  })
  const items = data.items
  // 页面上的勾选就是要确认的范围；打开时用服务端保存的勾选，改动随时同步回服务端
  const checkedDirs = items.filter((item) => item.selected).map((item) => item.film_dir)
  // 进行中的勾选同步和清单重拉（含静默重拉）次数
  const [syncCount, setSyncCount] = useState(0)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const selectAction = useApiAction((dirs: string[], selected: boolean) => selectCandidates(dirs, selected))
  const keepAction = useApiAction((item: ActressCandidateItem) => keepCandidates([item.film_dir]), {
    successMessage: (_data, item) => `已保留 ${item.number}，移到保留名单`,
    onSuccess: (_data, item) =>
      setData((prev) => {
        const base = prev ?? EMPTY_CANDIDATES
        const rest = base.items.filter((row) => row.film_dir !== item.film_dir)
        return { ...base, items: rest, total: rest.length }
      }),
  })
  const checkAction = useApiAction(
    async (dirs: string[]) => {
      let checked = 0
      for (let start = 0; start < dirs.length; start += CHECK_CHUNK) {
        const res = await checkCandidatesRemote(dirs.slice(start, start + CHECK_CHUNK))
        checked += res.count
      }
      return checked
    },
    { successMessage: (count) => `已检查 ${count} 部` },
  )
  const createAction = useApiAction((dirs: string[]) => createDeleteBatch(dirs), {
    successMessage: (_data, dirs) => `已开始删除 ${dirs.length} 部`,
    onSuccess: (res) => onBatchCreated(res.batch_id),
  })

  // 同步中：勾选写库、清单重拉、检查 115、保留、建删除批次任一在途。
  // 这期间页面勾选可能被重拉回来的旧数据覆盖，所以勾选、全选、全不选、检查、刷新和确认删除一律不可点
  const syncing =
    loading ||
    syncCount > 0 ||
    selectAction.loading ||
    checkAction.loading ||
    keepAction.loading ||
    createAction.loading
  // 确认框的回调里要读最新状态，放进 ref
  const latestRef = useRef({ data, syncing })
  useEffect(() => {
    latestRef.current = { data, syncing }
  })

  const withSync = async (work: () => Promise<unknown>) => {
    setSyncCount((count) => count + 1)
    try {
      await work()
    } finally {
      setSyncCount((count) => count - 1)
    }
  }

  /** 改勾选：先改页面，再同步到服务端；同步失败时按服务端重新拉取 */
  const toggle = (dirs: string[], selected: boolean) =>
    withSync(async () => {
      if (!dirs.length) return
      const targets = new Set(dirs)
      setData((prev) => {
        const base = prev ?? EMPTY_CANDIDATES
        return {
          ...base,
          items: base.items.map((item) => (targets.has(item.film_dir) ? { ...item, selected } : item)),
        }
      })
      const result = await selectAction.run(dirs, selected)
      if (!result.ok) await reload({ silent: true })
    })

  const checkRemote = async () => {
    await checkAction.run(checkedDirs)
    // 出错时前面几批也可能已写入结果，一样重新拉取
    await withSync(() => reload({ silent: true }))
  }

  const confirmDelete = () => {
    // 确认框里显示的就是这一刻页面上勾选的这些片子
    const dirs = checkedDirs
    const shownData = data
    if (!dirs.length || syncing || confirmOpen) return
    setConfirmOpen(true)
    void modal.confirm({
      title: `删除 ${dirs.length} 部片子`,
      content: `将删除 ${dirs.length} 部片子的 115 原文件和本地 STRM，115 文件进回收站。确定？`,
      okText: '确定删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onCancel: () => setConfirmOpen(false),
      onOk: async () => {
        try {
          // 框打开期间清单重拉过、勾选变过或正在同步：不发送框里的旧快照，让用户看清后重新确认
          const latest = latestRef.current
          if (latest.data !== shownData || latest.syncing) {
            message.warning('清单有变化，请重新确认')
            return
          }
          const result = await createAction.run(dirs)
          // 409：清单有变化、删除任务在跑或功能未开启；提示已显示后端原话，重新拉取清单，留在本页
          if (!result.ok && errorStatus(result.error) === 409) await withSync(() => reload())
        } finally {
          setConfirmOpen(false)
        }
      },
    })
  }

  const columns: ColumnsType<ActressCandidateItem> = [
    {
      title: '勾选',
      key: 'selected',
      width: 60,
      render: (_value, row) => (
        <Checkbox
          aria-label={`勾选 ${row.number}`}
          checked={row.selected}
          disabled={syncing}
          onChange={(event) => void toggle([row.film_dir], event.target.checked)}
        />
      ),
    },
    { title: '番号', dataIndex: 'number', width: 120 },
    { title: '标题', dataIndex: 'title', render: (value: string | null) => value ?? '-' },
    { title: '因为', dataIndex: 'black_names', width: 140, render: (names: string[]) => names.join('、') || '-' },
    {
      title: '同片演员',
      dataIndex: 'other_actors',
      render: (actors: ActressFilmActor[]) =>
        actors.length ? actors.map((actor) => `${actor.name}（${ACTOR_STATUS_LABELS[actor.status]}）`).join('、') : '-',
    },
    {
      title: '115 状态',
      key: 'remote',
      width: 200,
      render: (_value, row) =>
        row.remote_state === 'error' ? (
          <Text type="danger">{`有问题：${row.remote_note ?? '未知原因'}`}</Text>
        ) : (
          <ToneLabel entry={REMOTE_STATE[row.remote_state]} />
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_value, row) => (
        <Button size="small" disabled={syncing} onClick={() => void keepAction.run(row)}>
          保留
        </Button>
      ),
    },
  ]

  const uncheckedDirs = items.filter((item) => !item.selected).map((item) => item.film_dir)

  return (
    <>
      {modalHolder}
      <div style={{ marginBottom: 12 }}>
        <DataToolbar
          left={
            <>
              <Text strong>{`待删 ${items.length} 部，本次勾选 ${checkedDirs.length} 部`}</Text>
              <Button
                size="small"
                disabled={!uncheckedDirs.length || syncing}
                onClick={() => void toggle(uncheckedDirs, true)}
              >
                全选
              </Button>
              <Button
                size="small"
                disabled={!checkedDirs.length || syncing}
                onClick={() => void toggle(checkedDirs, false)}
              >
                全不选
              </Button>
            </>
          }
          right={
            <>
              <Button icon={<ReloadOutlined />} disabled={syncing} onClick={() => void withSync(() => reload())}>
                刷新
              </Button>
              <Button
                disabled={!checkedDirs.length || syncing}
                loading={checkAction.loading}
                onClick={() => void checkRemote()}
              >
                检查 115
              </Button>
              <Button
                type="primary"
                danger
                // 同步中或确认框已打开时不让再点，免得按旧清单建批次或叠出两个确认框
                disabled={!checkedDirs.length || syncing || confirmOpen}
                loading={createAction.loading}
                onClick={confirmDelete}
              >
                确认删除
              </Button>
            </>
          }
        />
      </div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
        不勾选 = 这次不删，留在清单里。「检查 115」只读查看勾选的片子在 115 上是否还在，不删任何文件。
      </Text>
      {/* 不分页：勾选的片子都会被删，要让每一部都在页面上看得到 */}
      <Table<ActressCandidateItem>
        rowKey="film_dir"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
        locale={{ emptyText: '待删清单是空的' }}
      />
    </>
  )
}

// ---------- 历史批次 ----------

function FileLines({ files }: { files: ActressDeleteBatchFileItem[] }) {
  if (!files.length) return <>-</>
  return (
    <Space orientation="vertical" size={2}>
      {files.map((file) => (
        <div key={file.id}>
          <Space size={6} wrap>
            <Text>{FILE_GROUP_LABELS[file.group]}</Text>
            <ToneLabel entry={FILE_STATUS[file.status]} />
            <Text type="secondary" style={{ wordBreak: 'break-all' }}>
              {file.target}
            </Text>
          </Space>
          {file.error && (
            <div>
              <Text type="danger">{file.error}</Text>
            </div>
          )}
        </div>
      ))}
    </Space>
  )
}

/** 批次详情：运行中每 3 秒刷新一次，结束后停止；从运行中变为结束时通知外面刷新列表 */
function BatchDetail({
  batchId,
  waitFinishedAt,
  onSettled,
  onClose,
}: {
  batchId: number
  waitFinishedAt?: string | null
  onSettled: () => void
  onClose: () => void
}) {
  const [detail, setDetail] = useState<ActressDeleteBatchDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(true)
  // 最新回调放进 ref，轮询不因回调变化重启
  const onSettledRef = useRef(onSettled)
  useEffect(() => {
    onSettledRef.current = onSettled
  })

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    let wasActive = false

    const load = async () => {
      try {
        const data = await getDeleteBatch(batchId)
        if (cancelled) return
        setDetail(data)
        setError(null)
        const active =
          ACTIVE_BATCH_STATUSES.includes(data.status) ||
          (waitFinishedAt !== undefined && data.finished_at === waitFinishedAt)
        if (active) {
          wasActive = true
          timer = setTimeout(load, POLL_MS)
          return
        }
        setPolling(false)
        if (wasActive) onSettledRef.current()
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
        setPolling(false)
      }
    }
    void load()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [batchId, waitFinishedAt])

  const header = (
    <Space size={12} wrap style={{ marginBottom: 12 }}>
      <Title level={5} style={{ margin: 0 }}>
        {`批次 #${batchId}`}
      </Title>
      {detail && <ToneLabel entry={BATCH_STATUS[detail.status]} />}
      {polling && detail && (
        <Text type="secondary">
          {ACTIVE_BATCH_STATUSES.includes(detail.status) ? '执行中，每 3 秒自动刷新…' : '已提交重试，等待开始执行…'}
        </Text>
      )}
      <Button size="small" onClick={onClose}>
        收起
      </Button>
    </Space>
  )

  if (error) {
    return (
      <>
        {header}
        <Alert type="error" showIcon title={`批次详情加载失败：${error}`} />
      </>
    )
  }
  if (!detail) return header

  const filmCount = (status: FilmStatus) => detail.films.filter((film) => film.status === status).length
  const filmColumns: ColumnsType<ActressDeleteBatchFilmItem> = [
    {
      title: '番号',
      key: 'number',
      width: 200,
      render: (_value, film) => (
        <>
          <div>{film.number}</div>
          <Text type="secondary" style={{ wordBreak: 'break-all' }}>
            {film.film_dir}
          </Text>
        </>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (value: FilmStatus) => <ToneLabel entry={FILM_STATUS[value]} />,
    },
    {
      title: '原因 / 错误',
      key: 'reason',
      width: 220,
      render: (_value, film) => (
        <>
          {film.reason && <div>{film.reason}</div>}
          {film.error && <Text type="danger">{film.error}</Text>}
          {!film.reason && !film.error && '-'}
        </>
      ),
    },
    { title: '文件', dataIndex: 'files', render: (files: ActressDeleteBatchFileItem[]) => <FileLines files={files} /> },
  ]

  return (
    <>
      {header}
      <Space orientation="vertical" size={4} style={{ display: 'flex', marginBottom: 12 }}>
        <Text>
          {`共 ${detail.films.length} 部：已删除 ${filmCount('deleted')}，失败 ${filmCount('failed')}，` +
            `跳过 ${filmCount('skipped')}，待执行 ${filmCount('pending')}`}
        </Text>
        <Text type="secondary">
          创建 <TimeText value={detail.created_at} />
          {detail.started_at && (
            <>
              {'，开始 '}
              <TimeText value={detail.started_at} />
            </>
          )}
          {detail.finished_at && (
            <>
              {'，结束 '}
              <TimeText value={detail.finished_at} />
            </>
          )}
          {`，Jellyfin：${detail.jellyfin_refresh ? JELLYFIN_REFRESH_LABELS[detail.jellyfin_refresh] : '-'}`}
        </Text>
        {detail.note && <Alert type="warning" showIcon title={detail.note} />}
      </Space>
      <Table<ActressDeleteBatchFilmItem>
        rowKey="id"
        size="small"
        columns={filmColumns}
        dataSource={detail.films}
        pagination={false}
        locale={{ emptyText: '这个批次没有片子' }}
      />
    </>
  )
}

function BatchesTab({ openBatch, onOpen }: { openBatch: OpenBatch | null; onOpen: (next: OpenBatch | null) => void }) {
  const { data, loading, reload } = useApiQuery(() => listDeleteBatches(), [], { initialData: EMPTY_BATCHES })
  const open = (id: number, waitFinishedAt?: string | null) =>
    onOpen({ id, waitFinishedAt, token: (openBatch?.token ?? 0) + 1 })

  const resumeAction = useApiAction((row: ActressDeleteBatchSummary) => resumeDeleteBatch(row.id), {
    successMessage: (_data, row) => `批次 #${row.id} 已开始重试`,
    onSuccess: (_data, row) => {
      open(row.id, row.finished_at)
      void reload({ silent: true })
    },
  })

  const columns: ColumnsType<ActressDeleteBatchSummary> = [
    { title: '批次', dataIndex: 'id', width: 80, render: (value: number) => `#${value}` },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (value: BatchStatus) => <ToneLabel entry={BATCH_STATUS[value]} />,
    },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: (value: string) => <TimeText value={value} /> },
    {
      title: '结束时间',
      dataIndex: 'finished_at',
      width: 170,
      render: (value: string | null) => (value ? <TimeText value={value} /> : '-'),
    },
    {
      title: '结果',
      key: 'result',
      width: 220,
      render: (_value, row) =>
        `已删除 ${row.deleted_films}，失败 ${row.failed_films}，跳过 ${row.skipped_films}`,
    },
    {
      title: 'Jellyfin',
      dataIndex: 'jellyfin_refresh',
      width: 110,
      render: (value: string | null) => (value ? JELLYFIN_REFRESH_LABELS[value] : '-'),
    },
    { title: '备注', dataIndex: 'note', render: (value: string | null) => value ?? '-' },
    {
      title: '操作',
      key: 'actions',
      width: 170,
      render: (_value, row) => (
        <Space size={4}>
          <Button size="small" onClick={() => open(row.id)}>
            查看
          </Button>
          {RESUMABLE_BATCH_STATUSES.includes(row.status) && (
            <Button size="small" disabled={resumeAction.loading} onClick={() => void resumeAction.run(row)}>
              重试失败的
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <DataToolbar
          right={
            <Button icon={<ReloadOutlined />} onClick={() => void reload()}>
              刷新
            </Button>
          }
        />
      </div>
      <Table<ActressDeleteBatchSummary>
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={data.items}
        pagination={data.items.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
        locale={{ emptyText: '还没有删除批次' }}
        style={{ marginBottom: 20 }}
      />
      {openBatch && (
        <BatchDetail
          key={`${openBatch.id}-${openBatch.token}`}
          batchId={openBatch.id}
          waitFinishedAt={openBatch.waitFinishedAt}
          onSettled={() => void reload({ silent: true })}
          onClose={() => onOpen(null)}
        />
      )}
    </>
  )
}

// ---------- 保留名单 ----------

function KeptTab() {
  const { data, loading, setData } = useApiQuery(() => listKept(), [], { initialData: EMPTY_KEPT })
  const removeAction = useApiAction((item: ActressKeptItem) => removeKept([item.film_dir]), {
    successMessage: (_data, item) => `已撤销保留 ${item.number}；仍应删除的话会回到待删清单`,
    onSuccess: (_data, item) =>
      setData((prev) => ({ items: (prev ?? EMPTY_KEPT).items.filter((row) => row.film_dir !== item.film_dir) })),
  })

  const columns: ColumnsType<ActressKeptItem> = [
    { title: '番号', dataIndex: 'number', width: 140 },
    {
      title: '目录',
      dataIndex: 'film_dir',
      render: (value: string) => <Text style={{ wordBreak: 'break-all' }}>{value}</Text>,
    },
    { title: '保留时间', dataIndex: 'created_at', width: 170, render: (value: string) => <TimeText value={value} /> },
    {
      title: '操作',
      key: 'actions',
      width: 110,
      render: (_value, row) => (
        <Button size="small" disabled={removeAction.loading} onClick={() => void removeAction.run(row)}>
          撤销保留
        </Button>
      ),
    },
  ]

  return (
    <Table<ActressKeptItem>
      rowKey="film_dir"
      size="small"
      loading={loading}
      columns={columns}
      dataSource={data.items}
      pagination={data.items.length > 50 ? { pageSize: 50, showSizeChanger: false } : false}
      locale={{ emptyText: '保留名单是空的' }}
    />
  )
}

export default function ActressDeletePage() {
  const [tab, setTab] = useState<TabKey>('candidates')
  const [openBatch, setOpenBatch] = useState<OpenBatch | null>(null)

  const handleBatchCreated = (batchId: number) => {
    setOpenBatch((prev) => ({ id: batchId, token: (prev?.token ?? 0) + 1 }))
    setTab('batches')
  }

  return (
    <PageScaffold
      title="女优删除"
      description="拉黑女优后，她的片子进入待删清单。只有在这里勾选并确认的片子才会删除：115 原文件进回收站，porn_tv1 的 STRM 和 302porn_tv1 的番号目录一并删除。"
    >
      <SurfacePanel>
        {/* 切换标签时卸载其他标签，每次切回都重新拉取 */}
        <Tabs
          activeKey={tab}
          onChange={(key) => setTab(key as TabKey)}
          destroyOnHidden
          items={[
            {
              key: 'candidates',
              label: '待删清单',
              children: <CandidatesTab onBatchCreated={handleBatchCreated} />,
            },
            {
              key: 'batches',
              label: '历史批次',
              children: <BatchesTab openBatch={openBatch} onOpen={setOpenBatch} />,
            },
            { key: 'kept', label: '保留名单', children: <KeptTab /> },
          ]}
        />
      </SurfacePanel>
    </PageScaffold>
  )
}
