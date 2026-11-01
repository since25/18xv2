import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

const api = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), postForm: vi.fn(),
}))

vi.mock('@/api/client', () => ({ api }))

import ImportsPage from './ImportsPage'
import NodesPage from './NodesPage'
import KeywordExtractorPage from './KeywordExtractorPage'
import KeywordsPage from './KeywordsPage'
import KeywordDuplicatesPage from './KeywordDuplicatesPage'
import HitsPage from './HitsPage'

const emptyResponse = {
  items: [], total: 0, records: [], clients: [], cookies: [], pairs: [], preview: [], suggestions: [],
  keywords: [], keyword_counts: {},
}

function renderPage(page: ReactNode) {
  return render(<MemoryRouter>{page}</MemoryRouter>)
}

describe('数据组页面冒烟渲染', () => {
  beforeEach(() => {
    api.get.mockImplementation((path: string) => {
      if (path.includes('/keywords/operation-logs') || path.includes('/keywords/hits?')) return Promise.resolve([])
      return Promise.resolve(emptyResponse)
    })
    api.post.mockResolvedValue(emptyResponse)
    api.patch.mockResolvedValue(emptyResponse)
    api.delete.mockResolvedValue(emptyResponse)
    api.postForm.mockResolvedValue(emptyResponse)
  })

  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  const cases: Array<[string, ReactNode, string]> = [
    ['导入批次', <ImportsPage />, '导入批次'],
    ['目录树内容', <NodesPage />, '目录树内容'],
    ['关键词提取器', <KeywordExtractorPage />, '关键词提取器'],
    ['关键词管理台', <KeywordsPage />, '关键词管理台'],
    ['重复词扫描', <KeywordDuplicatesPage />, '重复词扫描'],
    ['命中重建', <HitsPage />, '命中重建'],
  ]

  it.each(cases)('渲染 %s 的 PageScaffold 标题', async (_name, page, title) => {
    renderPage(page)
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
  })
})
