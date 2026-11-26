import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { message } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ActressDetail, ActressListResponse } from '@/api/actresses'

const listActresses = vi.fn()
const getActress = vi.fn()
const setActressStatus = vi.fn()
const addActressAlias = vi.fn()
const removeActressAlias = vi.fn()
const mergeActress = vi.fn()

vi.mock('@/api/actresses', () => ({
  listActresses: (...args: unknown[]) => listActresses(...args),
  getActress: (...args: unknown[]) => getActress(...args),
  setActressStatus: (...args: unknown[]) => setActressStatus(...args),
  addActressAlias: (...args: unknown[]) => addActressAlias(...args),
  removeActressAlias: (...args: unknown[]) => removeActressAlias(...args),
  mergeActress: (...args: unknown[]) => mergeActress(...args),
  actressImageUrl: (id: number) => `/api/actresses/${id}/image`,
}))

const { default: ActressesPage } = await import('./ActressesPage')

// antd 两个汉字的按钮会在字间插空格，按钮名按「字间可有空白」匹配
function buttonName(label: string) {
  return new RegExp(`^${[...label].join('\\s*')}$`)
}

// 测试数据全部是占位名（甲、乙、丙）和占位番号
function makeList(): ActressListResponse {
  return {
    items: [
      { id: 1, canonical_name: '甲', aliases: ['甲二'], status: 'none', film_count: 23, candidate_count: 0 },
      { id: 2, canonical_name: '乙', aliases: [], status: 'blacklist', film_count: 5, candidate_count: 5 },
    ],
    total: 2,
    counts: { none: 1840, blacklist: 12, whitelist: 30 },
  }
}

function makeDetail(overrides: Partial<ActressDetail> = {}): ActressDetail {
  return {
    id: 1,
    canonical_name: '甲',
    aliases: ['甲二'],
    alias_items: [{ id: 7, alias: '甲二' }],
    status: 'none',
    film_count: 1,
    candidate_count: 0,
    marks: [
      {
        from_status: 'blacklist',
        to_status: 'none',
        source: 'web',
        media_item_id: null,
        note: null,
        created_at: '2026-11-20T10:00:00Z',
      },
    ],
    films: [
      {
        film_dir: '/strm/甲/ABC-001',
        number: 'ABC-001',
        title: '示例标题',
        actors: [
          { name: '甲', status: 'none' },
          { name: '丙', status: 'whitelist' },
        ],
        protected: true,
        in_candidates: false,
      },
    ],
    ...overrides,
  }
}

describe('ActressesPage', () => {
  beforeEach(() => {
    listActresses.mockResolvedValue(makeList())
    getActress.mockResolvedValue(makeDetail())
    vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.restoreAllMocks()
  })

  it('按状态显示计数并列出女优', async () => {
    render(<ActressesPage />)
    expect(await screen.findByText('甲')).toBeInTheDocument()
    expect(screen.getByText('1840')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('30')).toBeInTheDocument()
    expect(screen.getByText('别名：甲二')).toBeInTheDocument()
    expect(screen.getByText('乙')).toBeInTheDocument()
    expect(screen.getByText('23 部')).toBeInTheDocument()
    expect(screen.getByText('草稿中 5 部')).toBeInTheDocument()
    expect(listActresses).toHaveBeenCalledWith(expect.objectContaining({ sort: 'film_count', page: 1 }))
  })

  it('点拉黑后调用 setActressStatus 并提示放进草稿的部数', async () => {
    setActressStatus.mockResolvedValue({ changed: 1, candidates_added: 3, candidates_removed: 0 })
    render(<ActressesPage />)
    const row = (await screen.findByText('甲')).closest('tr') as HTMLElement
    fireEvent.click(within(row).getByRole('button', { name: buttonName('拉黑') }))
    await waitFor(() =>
      expect(setActressStatus).toHaveBeenCalledWith({ actress_ids: [1], status: 'blacklist', source: 'web' }),
    )
    await waitFor(() => expect(message.success).toHaveBeenCalledWith('已放进删除草稿 3 部'))
    // 改完重新拉取列表
    await waitFor(() => expect(listActresses.mock.calls.length).toBeGreaterThan(1))
  })

  it('头像加载失败时显示占位', async () => {
    render(<ActressesPage />)
    const img = await screen.findByAltText('甲')
    expect(img).toHaveAttribute('src', '/api/actresses/1/image')
    fireEvent.error(img)
    expect(screen.queryByAltText('甲')).not.toBeInTheDocument()
    expect(screen.getByLabelText('甲 没有头像')).toBeInTheDocument()
  })

  it('详情抽屉里添加别名', async () => {
    addActressAlias.mockResolvedValue(
      makeDetail({
        aliases: ['甲二', '甲三'],
        alias_items: [
          { id: 7, alias: '甲二' },
          { id: 8, alias: '甲三' },
        ],
      }),
    )
    render(<ActressesPage />)
    fireEvent.click(await screen.findByText('甲'))
    await waitFor(() => expect(getActress).toHaveBeenCalledWith(1))
    // 她的片子：同片演员状态和是否受保护
    expect(await screen.findByText('ABC-001')).toBeInTheDocument()
    expect(screen.getByText('甲（未标）、丙（白名单）')).toBeInTheDocument()
    expect(screen.getByText('受保护')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('新别名'), { target: { value: '甲三' } })
    fireEvent.click(screen.getByRole('button', { name: buttonName('添加') }))
    await waitFor(() => expect(addActressAlias).toHaveBeenCalledWith(1, '甲三'))
    expect(await screen.findByText('甲三')).toBeInTheDocument()
  })

  it('详情抽屉里删除别名', async () => {
    removeActressAlias.mockResolvedValue(makeDetail({ aliases: [], alias_items: [] }))
    render(<ActressesPage />)
    fireEvent.click(await screen.findByText('甲'))
    fireEvent.click(await screen.findByRole('button', { name: '删除别名 甲二' }))
    await waitFor(() => expect(removeActressAlias).toHaveBeenCalledWith(1, 7))
    // 用接口返回的新详情刷新抽屉，并重新拉取列表
    expect(await screen.findByText('没有别名')).toBeInTheDocument()
    await waitFor(() => expect(listActresses.mock.calls.length).toBeGreaterThan(1))
  })

  it('选中合并目标后再搜别的名字，确认框仍显示选中的目标', async () => {
    render(<ActressesPage />)
    fireEvent.click(await screen.findByText('甲'))
    await waitFor(() => expect(getActress).toHaveBeenCalledWith(1))
    await screen.findByText('ABC-001')

    listActresses.mockResolvedValue({
      items: [{ id: 2, canonical_name: '乙', aliases: [], status: 'blacklist', film_count: 5, candidate_count: 5 }],
      total: 1,
      counts: { none: 0, blacklist: 1, whitelist: 0 },
    })
    const select = screen.getByLabelText('合并目标')
    fireEvent.mouseDown(select)
    fireEvent.change(select, { target: { value: '乙' } })
    fireEvent.click(await screen.findByText('乙（黑名单，5 部）', { selector: '.ant-select-item-option-content' }))

    // 选好之后又输入别的搜索词，选项里已经没有乙
    listActresses.mockResolvedValue({
      items: [{ id: 3, canonical_name: '丙', aliases: [], status: 'whitelist', film_count: 2, candidate_count: 0 }],
      total: 1,
      counts: { none: 0, blacklist: 0, whitelist: 1 },
    })
    fireEvent.mouseDown(select)
    fireEvent.change(select, { target: { value: '丙' } })
    expect(await screen.findByText('丙（白名单，2 部）', { selector: '.ant-select-item-option-content' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: buttonName('合并') }))
    expect(await screen.findByText('把「甲」合并进「乙」？')).toBeInTheDocument()
    expect(screen.getByText(/对方是未标时，会继承她的黑名单\/白名单状态/)).toBeInTheDocument()
  })
})
