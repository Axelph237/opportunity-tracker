/**
 * Clickable table header. Click to sort by that column, click again to flip direction.
 *
 * `sticky` pins the header inside a scrolling table body. The underline is drawn as
 * an inset shadow because a border on a `border-collapse` table scrolls away with
 * the rows.
 */
import { SortCaret } from './icons'

// Written out rather than composed as `text-${align}`. Tailwind generates its
// classes by scanning the source for literal names, so an interpolated one is
// never emitted and the alignment silently does nothing.
const ALIGN = { left: 'text-left', center: 'text-center', right: 'text-right' }

export default function SortableTh({
  column,
  label,
  sort,
  order,
  onSort,
  align = 'left',
  sticky = false,
  className = '',
}) {
  const active = sort === column
  const nextOrder = active && order === 'desc' ? 'asc' : 'desc'
  const pinned = sticky ? 'sticky top-0 z-10 bg-surface shadow-[inset_0_-1px_0_var(--color-outline-variant)]' : ''

  if (!column) {
    return (
      <th className={`label-data px-3 py-2 font-normal ${ALIGN[align]} ${pinned} ${className}`}>
        {label}
      </th>
    )
  }

  return (
    <th
      className={`px-3 py-2 font-normal ${ALIGN[align] || ALIGN.left} ${pinned} ${className}`}
      aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={() => onSort(column, nextOrder)}
        title={`Sort by ${label}`}
        className={`label-data inline-flex items-center gap-1 transition-colors hover:text-primary ${
          active ? 'text-primary' : ''
        }`}
      >
        {label}
        <SortCaret active={active} order={order} className={active ? 'h-3.5 w-3.5' : 'h-3.5 w-3.5 opacity-40'} />
      </button>
    </th>
  )
}
