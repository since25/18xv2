import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PageScaffold from './PageScaffold'

describe('PageScaffold', () => {
  it('renders title, description, actions, stats, and children', () => {
    render(
      <PageScaffold
        title="文件去重"
        description="扫描本地目录树"
        actions={<button>刷新</button>}
        stats={[
          { label: '候选组', value: 12 },
          { label: '删除计划', value: 3 },
        ]}
      >
        <section>候选列表</section>
      </PageScaffold>,
    )

    expect(screen.getByRole('heading', { name: '文件去重' })).toBeInTheDocument()
    expect(screen.getByText('扫描本地目录树')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument()
    expect(screen.getByText('候选组')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('候选列表')).toBeInTheDocument()
  })
})
