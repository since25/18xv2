import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PageScaffold from './PageScaffold'

describe('PageScaffold', () => {
  it('renders title, description, actions, stats, children, and custom root class', () => {
    const { container } = render(
      <PageScaffold
        className="dedupe-page"
        title="文件去重"
        titleLevel={2}
        description="扫描本地目录树"
        actions={<button>刷新</button>}
        stats={[
          { key: 'candidate-groups', label: '候选组', value: 12 },
          { key: 'delete-plans', label: '删除计划', value: 3 },
        ]}
      >
        <section>候选列表</section>
      </PageScaffold>,
    )

    expect(screen.getByRole('heading', { name: '文件去重', level: 2 })).toBeInTheDocument()
    expect(screen.getByText('扫描本地目录树')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument()
    expect(screen.getByText('候选组')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('候选列表')).toBeInTheDocument()
    expect(container.firstElementChild).toHaveClass('page-shell', 'dedupe-page')
    expect(container.querySelector('header.page-header')).toBeInTheDocument()
  })

  it('defaults to a level 3 title and renders cleanly without optional header content', () => {
    const { container } = render(
      <PageScaffold title="任务概览">
        <section>任务列表</section>
      </PageScaffold>,
    )

    expect(screen.getByRole('heading', { name: '任务概览', level: 3 })).toBeInTheDocument()
    expect(screen.getByText('任务列表')).toBeInTheDocument()
    expect(container.querySelector('.metric-strip')).not.toBeInTheDocument()
  })
})
