import { useState } from 'react'
import { Checkbox, EditActions, Field, TextArea, TextInput } from './editing'
import Dropdown from './Dropdown'
import { PlusIcon, TrashIcon } from './icons'

/**
 * What each kind of record is, and what a resume prints for it.
 *
 * The same table the backend's layout registry encodes, from the side the user
 * sees: a skill group has no location and a project has no employer, so asking
 * for them is noise. One row per kind, rather than a conditional per field.
 */
export const ENTRY_KINDS = [
  { value: 'experience', label: 'Experience', title: 'Role', fields: ['organization', 'location', 'dates', 'url'] },
  { value: 'education', label: 'Education', title: 'Degree', fields: ['organization', 'location', 'dates', 'url'] },
  { value: 'project', label: 'Project', title: 'Project', fields: ['detail', 'dates', 'url'] },
  { value: 'skill_group', label: 'Skill group', title: 'Group', fields: [], inline: true },
  { value: 'award', label: 'Award', title: 'Award', fields: ['organization', 'dates', 'url'] },
  { value: 'publication', label: 'Publication', title: 'Title', fields: ['detail', 'dates', 'url'] },
  { value: 'presentation', label: 'Presentation', title: 'Title', fields: ['organization', 'dates', 'url'] },
  { value: 'certification', label: 'Certification', title: 'Certificate', fields: ['organization', 'dates', 'url'] },
]

const KIND_OPTIONS = ENTRY_KINDS.map(({ value, label }) => ({ value, label }))
const KIND_BY_VALUE = Object.fromEntries(ENTRY_KINDS.map((kind) => [kind.value, kind]))

export const layoutFor = (kind) => KIND_BY_VALUE[kind] || KIND_BY_VALUE.experience

const BLANK = {
  kind: 'experience',
  title: '',
  organization: '',
  location: '',
  start_date: '',
  end_date: '',
  is_current: false,
  url: '',
  detail: '',
}

const FIELD_KEYS = {
  organization: ['organization'],
  location: ['location'],
  dates: ['start_date', 'end_date', 'is_current'],
  url: ['url'],
  detail: ['detail'],
}

function formOf(entry) {
  if (!entry) return { ...BLANK }
  return Object.fromEntries(
    Object.keys(BLANK).map((key) => [key, entry[key] ?? BLANK[key]]),
  )
}

/**
 * Add or edit one record in the experience bank. Lives inside a SlidePanel.
 *
 * Bullets are edited here with the rest of the record and handed back whole,
 * so one Save covers the entry and its bullets and Cancel discards both. The
 * caller works out which bullets are new, changed or gone.
 */
export default function BankEntryForm({ entry, onSave, onDelete, onCancel, busy }) {
  const [form, setForm] = useState(() => formOf(entry))
  const [bullets, setBullets] = useState(() => (entry?.bullets || []).map((b) => ({ id: b.id, text: b.text })))
  const layout = layoutFor(form.kind)
  const shows = (field) => layout.fields.includes(field)

  const set = (patch) => setForm((current) => ({ ...current, ...patch }))

  // Switching kind drops whatever the old kind collected and the new one does
  // not show. Leaving it behind would store a location nobody can see or edit.
  const setKind = (kind) => {
    const next = layoutFor(kind)
    const cleared = Object.entries(FIELD_KEYS)
      .filter(([field]) => !next.fields.includes(field))
      .flatMap(([, keys]) => keys.map((key) => [key, BLANK[key]]))
    setForm((current) => ({ ...current, ...Object.fromEntries(cleared), kind }))
  }

  const setBullet = (index, text) =>
    setBullets((current) => current.map((bullet, i) => (i === index ? { ...bullet, text } : bullet)))

  const noun = layout.inline ? 'term' : 'bullet'

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        onSave(
          { ...form, title: form.title.trim() },
          bullets.map((bullet) => ({ ...bullet, text: bullet.text.trim() })).filter((bullet) => bullet.text),
        )
      }}
    >
      <Field label="Kind">
        <Dropdown value={form.kind} onChange={setKind} options={KIND_OPTIONS} ariaLabel="Kind" className="w-full" />
      </Field>

      <Field label={layout.title}>
        <TextInput value={form.title} onChange={(title) => set({ title })} required />
      </Field>

      {shows('organization') ? (
        <Field label="Organization">
          <TextInput value={form.organization} onChange={(organization) => set({ organization })} />
        </Field>
      ) : null}

      {shows('location') ? (
        <Field label="Location">
          <TextInput value={form.location} onChange={(location) => set({ location })} />
        </Field>
      ) : null}

      {shows('detail') ? (
        <Field label="Detail" hint="The tech stack or one-line tagline printed beside the heading.">
          <TextInput value={form.detail} onChange={(detail) => set({ detail })} />
        </Field>
      ) : null}

      {shows('dates') ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-3">
            <Field label="From" hint="As you want it printed.">
              <TextInput value={form.start_date} onChange={(start_date) => set({ start_date })} placeholder="Jun 2026" />
            </Field>
            <Field label="To">
              <TextInput
                value={form.is_current ? '' : form.end_date}
                onChange={(end_date) => set({ end_date })}
                placeholder="Sep 2026"
                disabled={form.is_current}
              />
            </Field>
          </div>
          <Checkbox
            checked={form.is_current}
            onChange={(is_current) => set({ is_current, end_date: is_current ? '' : form.end_date })}
          >
            Still going — print “Present”
          </Checkbox>
        </div>
      ) : null}

      {shows('url') ? (
        <Field label="Link">
          <TextInput value={form.url} onChange={(url) => set({ url })} placeholder="https://" />
        </Field>
      ) : null}

      <div className="space-y-2">
        <span className="label-data block">{layout.inline ? 'Terms' : 'Bullets'}</span>
        {layout.inline ? null : (
          <p className="font-mono text-data text-on-surface-variant">
            Start with a strong verb, no full stop, one or two lines. Say what you did, why, and what
            happened.
          </p>
        )}
        {bullets.map((bullet, index) => (
          <div key={bullet.id ?? `new-${index}`} className="flex items-start gap-2">
            {layout.inline ? (
              <TextInput value={bullet.text} onChange={(text) => setBullet(index, text)} aria-label={`Term ${index + 1}`} />
            ) : (
              <TextArea value={bullet.text} onChange={(text) => setBullet(index, text)} rows={2} aria-label={`Bullet ${index + 1}`} />
            )}
            <button
              type="button"
              aria-label={`Remove ${noun} ${index + 1}`}
              className="mt-[6px] shrink-0 text-on-surface-variant transition-colors hover:text-error"
              onClick={() => setBullets((current) => current.filter((_, i) => i !== index))}
            >
              <TrashIcon />
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn"
          onClick={() => setBullets((current) => [...current, { id: null, text: '' }])}
        >
          <PlusIcon />
          Add {noun}
        </button>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-outline-variant pt-4">
        <EditActions
          onCancel={onCancel}
          busy={busy}
          dirty={Boolean(form.title.trim())}
          saveLabel={entry ? 'Save changes' : 'Add to bank'}
        />
        {entry ? (
          <button
            type="button"
            className="btn hover:border-error hover:text-error"
            onClick={onDelete}
            disabled={busy}
          >
            <TrashIcon />
            Delete
          </button>
        ) : null}
      </div>
    </form>
  )
}
