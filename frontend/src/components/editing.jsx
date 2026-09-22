import { useState } from 'react'
import Dropdown from './Dropdown'
import { PlusIcon, TrashIcon } from './icons'

/**
 * Form primitives shared by every manual editor (listing, source, role analysis).
 * They wrap the same `.field` / `.label-data` styles the rest of the app uses so an
 * edit form looks like the page it sits in rather than a separate widget.
 */

export function Field({ label, hint, className = '', children }) {
  return (
    <label className={`block space-y-1 ${className}`}>
      <span className="label-data block">{label}</span>
      {children}
      {hint ? <span className="block font-mono text-data text-on-surface-variant">{hint}</span> : null}
    </label>
  )
}

export function TextInput({ value, onChange, ...rest }) {
  return <input className="field" value={value ?? ''} onChange={(e) => onChange(e.target.value)} {...rest} />
}

export function TextArea({ value, onChange, rows = 4, ...rest }) {
  return (
    <textarea
      className="field"
      rows={rows}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      {...rest}
    />
  )
}

export function NumberInput({ value, onChange, ...rest }) {
  return (
    <input
      type="number"
      className="field font-mono"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      {...rest}
    />
  )
}

export function Select({ value, onChange, options, placeholder }) {
  return (
    <Dropdown
      value={value}
      onChange={(next) => onChange(next ?? null)}
      options={options}
      placeholder={placeholder}
      className="w-full"
    />
  )
}

export function Checkbox({ checked, onChange, children }) {
  return (
    <label className="flex items-center gap-2">
      <input
        type="checkbox"
        className="h-4 w-4 accent-primary"
        checked={Boolean(checked)}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>{children}</span>
    </label>
  )
}

/**
 * Free-form list of strings.
 *
 * `layout="chips"` suits short values (tags, skills). `layout="rows"` gives each
 * value a full-width line, which is the only readable option for sentence-length
 * entries such as strengths, where chips wrap into an unreadable block.
 */
export function StringListEditor({ values = [], onChange, placeholder = 'Add…', layout = 'chips' }) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const entry = draft.trim()
    if (!entry || values.includes(entry)) return setDraft('')
    onChange([...values, entry])
    setDraft('')
  }

  const remove = (index) => onChange(values.filter((_, i) => i !== index))

  return (
    <div className="space-y-2">
      {values.length && layout === 'rows' ? (
        <ul className="space-y-2">
          {values.map((entry, index) => (
            <li
              key={`${entry}-${index}`}
              className="flex items-start gap-3 rounded border border-outline-variant bg-surface px-3 py-2"
            >
              <span className="min-w-0 flex-1 text-on-surface">{entry}</span>
              <button
                type="button"
                aria-label={`Remove ${entry}`}
                className="mt-[2px] shrink-0 text-on-surface-variant transition-colors hover:text-error"
                onClick={() => remove(index)}
              >
                <TrashIcon />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {values.length && layout === 'chips' ? (
        <div className="flex flex-wrap gap-2">
          {values.map((entry, index) => (
            <span
              key={`${entry}-${index}`}
              className="inline-flex items-center gap-1 rounded border border-outline-variant bg-surface-container-high px-2 py-[2px] font-mono text-data text-on-surface"
            >
              {entry}
              <button
                type="button"
                aria-label={`Remove ${entry}`}
                className="text-on-surface-variant transition-colors hover:text-error"
                onClick={() => remove(index)}
              >
                <TrashIcon className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className="flex gap-2">
        <input
          className="field"
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // Enter adds an entry; it must not submit the surrounding form.
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button type="button" className="btn shrink-0" onClick={add} disabled={!draft.trim()}>
          <PlusIcon />
          Add
        </button>
      </div>
    </div>
  )
}

/**
 * A list of object rows with add and remove, used for the role analysis tables.
 * `renderRow(row, update)` draws one row's fields; `update(patch)` merges into it.
 */
export function RowListEditor({ rows = [], onChange, blank, renderRow, addLabel = 'Add row' }) {
  const update = (index, patch) =>
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))

  return (
    <div className="space-y-3">
      {rows.map((row, index) => (
        <div key={index} className="relative rounded border border-outline-variant bg-surface p-3 pr-10">
          {renderRow(row, (patch) => update(index, patch), index)}
          <button
            type="button"
            aria-label={`Remove row ${index + 1}`}
            title="Remove this row"
            className="absolute right-2 top-2 text-on-surface-variant transition-colors hover:text-error"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <TrashIcon />
          </button>
        </div>
      ))}
      <button type="button" className="btn" onClick={() => onChange([...rows, { ...blank }])}>
        <PlusIcon />
        {addLabel}
      </button>
    </div>
  )
}

/** Save / Cancel pair shared by the editors. */
export function EditActions({ onSave, onCancel, busy, dirty = true, saveLabel = 'Save changes' }) {
  return (
    <div className="flex items-center gap-3">
      <button type="submit" className="btn btn-primary" onClick={onSave} disabled={busy || !dirty}>
        {busy ? 'Saving…' : saveLabel}
      </button>
      <button type="button" className="btn" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
    </div>
  )
}
