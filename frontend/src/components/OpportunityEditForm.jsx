import { useMemo, useState } from 'react'
import {
  Checkbox,
  EditActions,
  Field,
  NumberInput,
  Select,
  StringListEditor,
  TextArea,
  TextInput,
} from './editing'
import { EXPERIENCE_LEVELS, OPPORTUNITY_TYPES } from '../api'

// Only these reach the PATCH body; everything else on a listing is derived.
const EDITABLE = [
  'title',
  'organization',
  'type',
  'location',
  'remote',
  'url',
  'description',
  'deadline',
  'experience_level',
  'relevance_score',
  'relevance_summary',
  'skill_matches',
  'tags',
  'notes',
  'is_active',
]

const toDraft = (opportunity) =>
  Object.fromEntries(EDITABLE.map((key) => [key, opportunity?.[key] ?? (key === 'remote' || key === 'is_active' ? false : null)]))

/**
 * Manual corrections to a scraped listing. Claude's extraction is a first pass —
 * a wrong deadline or a title truncated by the page's markup is fixed here.
 */
export default function OpportunityEditForm({ opportunity, onSave, onCancel, busy, error }) {
  const original = useMemo(() => toDraft(opportunity), [opportunity])
  const [draft, setDraft] = useState(original)

  const set = (patch) => setDraft((current) => ({ ...current, ...patch }))
  const dirty = JSON.stringify(draft) !== JSON.stringify(original)

  const submit = (event) => {
    event.preventDefault()
    // Send only what actually changed, so a partial edit cannot clobber a field.
    const changes = Object.fromEntries(
      EDITABLE.filter((key) => JSON.stringify(draft[key]) !== JSON.stringify(original[key])).map(
        (key) => [key, draft[key]],
      ),
    )
    onSave(changes)
  }

  const score = draft.relevance_score

  return (
    <form onSubmit={submit} className="space-y-5">
      {error ? (
        <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{error}</p>
      ) : null}

      <div className="grid grid-cols-2 gap-3">
        <Field label="Title" className="col-span-2">
          <TextInput required value={draft.title} onChange={(title) => set({ title })} />
        </Field>
        <Field label="Organization">
          <TextInput required value={draft.organization} onChange={(organization) => set({ organization })} />
        </Field>
        <Field label="Type">
          <Select value={draft.type} onChange={(type) => set({ type })} options={OPPORTUNITY_TYPES} />
        </Field>
        <Field label="Location">
          <TextInput value={draft.location} onChange={(location) => set({ location })} placeholder="Chicago, IL" />
        </Field>
        <Field label="Experience level">
          <Select
            value={draft.experience_level}
            onChange={(experience_level) => set({ experience_level })}
            options={EXPERIENCE_LEVELS}
            placeholder="Unspecified"
          />
        </Field>
        <Field label="URL" className="col-span-2">
          <TextInput required type="url" value={draft.url} onChange={(url) => set({ url })} />
        </Field>
        <Field label="Deadline" hint="Free text — the scraper stores whatever the page said.">
          <TextInput value={draft.deadline} onChange={(deadline) => set({ deadline })} placeholder="2026-12-01" />
        </Field>
        <Field label={`Relevance score${score === null || score === undefined ? '' : ` — ${Number(score) >= 7.5 ? 'strong match' : 'normal'}`}`}>
          <NumberInput
            min="0"
            max="10"
            step="0.1"
            value={score}
            onChange={(relevance_score) => set({ relevance_score })}
          />
        </Field>
      </div>

      <div className="flex flex-wrap gap-6 rounded border border-outline-variant bg-surface px-3 py-2">
        <Checkbox checked={draft.remote} onChange={(remote) => set({ remote })}>
          Remote
        </Checkbox>
        <Checkbox checked={draft.is_active} onChange={(is_active) => set({ is_active })}>
          Active
        </Checkbox>
      </div>

      <Field label="Why it matches">
        <TextArea
          value={draft.relevance_summary}
          onChange={(relevance_summary) => set({ relevance_summary })}
          rows={3}
        />
      </Field>

      <Field label="Description">
        <TextArea value={draft.description} onChange={(description) => set({ description })} rows={6} />
      </Field>

      <div>
        <span className="label-data block mb-2">Skill matches</span>
        <StringListEditor
          values={draft.skill_matches || []}
          onChange={(skill_matches) => set({ skill_matches })}
          placeholder="Add a skill…"
        />
      </div>

      <div>
        <span className="label-data block mb-2">Tags</span>
        <StringListEditor values={draft.tags || []} onChange={(tags) => set({ tags })} placeholder="Add a tag…" />
      </div>

      <Field label="Notes">
        <TextArea value={draft.notes} onChange={(notes) => set({ notes })} rows={3} />
      </Field>

      <EditActions onCancel={onCancel} busy={busy} dirty={dirty} />
    </form>
  )
}
