import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Pager, { DEFAULT_PAGE_SIZE } from './Pager'

function setup(props = {}) {
  const onPage = vi.fn()
  const onPageSize = vi.fn()
  render(
    <Pager
      page={0}
      pageSize={DEFAULT_PAGE_SIZE}
      total={137}
      onPage={onPage}
      onPageSize={onPageSize}
      label="listings"
      {...props}
    />,
  )
  return { onPage, onPageSize }
}

describe('Pager', () => {
  it('shows the range and the total, not just a page number', () => {
    setup()
    expect(screen.getByText('1–25 of 137 listings')).toBeInTheDocument()
    expect(screen.getByText('Page 1 of 6')).toBeInTheDocument()
  })

  it('counts the range from the current page', () => {
    setup({ page: 2 })
    expect(screen.getByText('51–75 of 137 listings')).toBeInTheDocument()
  })

  it('does not overstate the last page', () => {
    setup({ page: 5 })
    expect(screen.getByText('126–137 of 137 listings')).toBeInTheDocument()
  })

  it('cannot go back from the first page', () => {
    setup()
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
  })

  it('cannot go past the last page', () => {
    setup({ page: 5 })
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  })

  it('moves a page at a time', async () => {
    const user = userEvent.setup()
    const { onPage } = setup({ page: 2 })
    await user.click(screen.getByRole('button', { name: 'Next page' }))
    expect(onPage).toHaveBeenCalledWith(3)
    await user.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(onPage).toHaveBeenCalledWith(1)
  })

  it('collapses to a bare count when everything fits on one page', () => {
    // Controls that can only do nothing are worse than no controls.
    setup({ total: 12 })
    expect(screen.getByText('12 listings')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Next page' })).not.toBeInTheDocument()
  })

  it('handles an empty table without claiming a row', () => {
    setup({ total: 0 })
    expect(screen.getByText('0 listings')).toBeInTheDocument()
  })

  it('offers a page size', async () => {
    const user = userEvent.setup()
    const { onPageSize } = setup()
    await user.click(screen.getByRole('button', { name: /Rows per page/ }))
    await user.click(screen.getByRole('option', { name: '50 / page' }))
    expect(onPageSize).toHaveBeenCalledWith(50)
  })

  it('defaults to 25 rows', () => {
    expect(DEFAULT_PAGE_SIZE).toBe(25)
  })
})
