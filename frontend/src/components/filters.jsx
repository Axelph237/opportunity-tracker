// Shared filter controls. Every table toolbar is built from these so filtering
// looks and behaves the same on Opportunities, Applications, Sources and Logs.

import Dropdown from './Dropdown'
import { SortCaret } from './icons'
import { titleCase } from '../format'

export function SearchInput({ value, onChange, placeholder = 'Search…', className = 'max-w-xs' }) {
  return (
    <input
      type="search"
      className={`field ${className}`}
      placeholder={placeholder}
      value={value || ''}
      onChange={(event) => onChange(event.target.value || undefined)}
    />
  )
}

export function ToggleChip({ active, onClick, children, title }) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1 rounded border px-2 py-[3px] font-mono text-data transition-colors ${
        active ? 'border-primary bg-primary/15 text-primary' : 'border-outline-variant text-on-surface-variant hover:border-primary/50 hover:text-on-surface'
      }`}
    >
      {children}
    </button>
  )
}

/** Multi-select rendered as a row of toggle chips. */
export function ChipGroup({ label, options, selected = [], onChange }) {
  const toggle = (value) => {
    const next = selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value]
    onChange(next.length ? next : undefined)
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {label ? <span className="label-data mr-1">{label}</span> : null}
      {options.map((option) => {
        const value = typeof option === 'string' ? option : option.value
        const text = typeof option === 'string' ? titleCase(option) : option.label
        return (
          <ToggleChip key={value} active={selected.includes(value)} onClick={() => toggle(value)}>
            {text}
          </ToggleChip>
        )
      })}
    </div>
  )
}

export function SelectFilter({ value, onChange, options, placeholder, className = 'w-auto' }) {
  return (
    <Dropdown
      value={value}
      onChange={onChange}
      options={options}
      placeholder={placeholder}
      className={className}
      ariaLabel={placeholder}
    />
  )
}

/** Numeric min/max pair, used for the relevance score range. */
export function RangeFilter({ label, min, max, onChange, step = 0.5, bound = 10 }) {
  return (
    <div className="flex items-center gap-2">
      <span className="label-data">{label}</span>
      <input
        type="number"
        min="0"
        max={bound}
        step={step}
        className="field w-16 font-mono"
        placeholder="min"
        value={min ?? ''}
        onChange={(event) => onChange({ min: event.target.value === '' ? undefined : Number(event.target.value), max })}
      />
      <span className="text-on-surface-variant">–</span>
      <input
        type="number"
        min="0"
        max={bound}
        step={step}
        className="field w-16 font-mono"
        placeholder="max"
        value={max ?? ''}
        onChange={(event) => onChange({ min, max: event.target.value === '' ? undefined : Number(event.target.value) })}
      />
    </div>
  )
}

export function SortDirection({ order, onChange }) {
  return (
    <button
      type="button"
      className="btn"
      title="Toggle sort direction"
      onClick={() => onChange(order === 'asc' ? 'desc' : 'asc')}
    >
      <SortCaret active order={order} />
      {order === 'asc' ? 'Asc' : 'Desc'}
    </button>
  )
}

export function ClearFilters({ show, onClear }) {
  if (!show) return null
  return (
    <button type="button" className="btn" onClick={onClear}>
      Clear
    </button>
  )
}

export function ResultCount({ count, noun = 'result' }) {
  if (count === undefined || count === null) return null
  return (
    <span className="ml-auto font-mono text-data text-on-surface-variant">
      {count} {noun}
      {count === 1 ? '' : 's'}
    </span>
  )
}

/** True when anything beyond sort/order is set. */
export function hasActiveFilters(filters, ignore = ['sort', 'order']) {
  return Object.entries(filters || {}).some(([key, value]) => {
    if (ignore.includes(key)) return false
    if (value === undefined || value === null || value === '') return false
    if (Array.isArray(value)) return value.length > 0
    return true
  })
}
