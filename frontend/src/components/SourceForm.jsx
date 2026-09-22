import { useMemo, useState } from 'react'
import { Checkbox, EditActions, Field, Select, TextArea, TextInput } from './editing'
import { SOURCE_TYPES } from '../api'

const BLANK = {
  name: '',
  url: '',
  type: 'job_board',
  scrape_method: 'html',
  search_query: '',
  active: true,
  notes: '',
}

const FIELDS = ['name', 'url', 'type', 'scrape_method', 'search_query', 'active', 'notes']

/**
 * One form for both adding a source and editing an existing one. On edit it sends
 * only the changed fields, so it cannot silently overwrite a column it did not show.
 */
export default function SourceForm({ source, onSubmit, onCancel, busy, error, submitLabel }) {
  const original = useMemo(
    () => (source ? Object.fromEntries(FIELDS.map((key) => [key, source[key] ?? BLANK[key]])) : BLANK),
    [source],
  )
  const [draft, setDraft] = useState(original)
  const set = (patch) => setDraft((current) => ({ ...current, ...patch }))

  const editing = Boolean(source)
  const dirty = !editing || JSON.stringify(draft) !== JSON.stringify(original)

  const submit = (event) => {
    event.preventDefault()
    const payload = editing
      ? Object.fromEntries(FIELDS.filter((key) => draft[key] !== original[key]).map((key) => [key, draft[key]]))
      : { ...draft }
    if ('search_query' in payload) payload.search_query = payload.search_query || null
    if ('notes' in payload) payload.notes = payload.notes || null
    onSubmit(payload)
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error ? (
        <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{error}</p>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <Field label="Name">
          <TextInput required value={draft.name} onChange={(name) => set({ name })} placeholder="Fermilab Careers" />
        </Field>
        <Field label="URL">
          <TextInput
            required
            type="url"
            value={draft.url}
            onChange={(url) => set({ url })}
            placeholder="https://example.org/careers"
          />
        </Field>
        <Field label="Type">
          <Select value={draft.type} onChange={(type) => set({ type })} options={SOURCE_TYPES} />
        </Field>
        <Field label="Scrape method">
          <Select
            value={draft.scrape_method}
            onChange={(scrape_method) => set({ scrape_method })}
            options={['html', 'api', 'search_query']}
          />
        </Field>
        <Field
          label="Search query (optional)"
          className="col-span-2"
          hint="Substituted into {query} in the URL, or appended as ?q=… for the search_query method."
        >
          <TextInput
            value={draft.search_query}
            onChange={(search_query) => set({ search_query })}
            placeholder="quantum engineer"
          />
        </Field>
        <Field label="Notes" className="col-span-2">
          <TextArea
            value={draft.notes}
            onChange={(notes) => set({ notes })}
            rows={2}
            placeholder="Why this source is here, or what is wrong with it."
          />
        </Field>
      </div>

      <div className="rounded border border-outline-variant bg-surface px-3 py-2">
        <Checkbox checked={draft.active} onChange={(active) => set({ active })}>
          Active — included in every scrape run
        </Checkbox>
      </div>

      <EditActions
        onCancel={onCancel}
        busy={busy}
        dirty={dirty}
        saveLabel={submitLabel || (editing ? 'Save changes' : 'Add source')}
      />
    </form>
  )
}
