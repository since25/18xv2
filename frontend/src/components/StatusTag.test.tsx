import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import StatusTag from './StatusTag'

describe('StatusTag', () => {
  it('renders translated status text and its tone class', () => {
    render(<StatusTag domain="package" value="outdated" suffix="+3" />)

    expect(screen.getByText('有更新 (+3)')).toHaveClass('status-tag--warning')
  })
})
