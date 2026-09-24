import Dropdown from './Dropdown'
import { BackIcon, ChevronIcon } from './icons'

export const PAGE_SIZES = [25, 50, 100]
export const DEFAULT_PAGE_SIZE = 25

/**
 * Page controls for a table, with the range and the total spelled out.
 *
 * "1–25 of 137" rather than a bare page number: the useful question is almost
 * always how much there is altogether, and a page number alone cannot answer
 * it. Hidden entirely when everything fits on one page.
 */
export default function Pager({ page, pageSize, total, onPage, onPageSize, label = 'rows' }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const first = total === 0 ? 0 : page * pageSize + 1
  const last = Math.min((page + 1) * pageSize, total)

  if (total <= PAGE_SIZES[0] && page === 0) {
    return (
      <div className="flex items-center justify-end gap-3 py-3 font-mono text-data text-on-surface-variant">
        {total} {label}
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-3 py-3">
      <span className="font-mono text-data text-on-surface-variant">
        {first}–{last} of {total} {label}
      </span>

      <Dropdown
        ariaLabel="Rows per page"
        className="w-28"
        value={pageSize}
        onChange={(value) => onPageSize(Number(value))}
        options={PAGE_SIZES.map((size) => ({ value: size, label: `${size} / page` }))}
      />

      <div className="flex items-center gap-1">
        <button
          type="button"
          className="btn"
          aria-label="Previous page"
          disabled={page === 0}
          onClick={() => onPage(page - 1)}
        >
          <BackIcon />
        </button>
        <span className="min-w-[5.5rem] text-center font-mono text-data text-on-surface-variant">
          Page {page + 1} of {pages}
        </span>
        <button
          type="button"
          className="btn"
          aria-label="Next page"
          disabled={page + 1 >= pages}
          onClick={() => onPage(page + 1)}
        >
          <ChevronIcon />
        </button>
      </div>
    </div>
  )
}
