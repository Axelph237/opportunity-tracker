import { useMemo, useState } from 'react'
import {
  EditActions,
  Field,
  NumberInput,
  RowListEditor,
  Select,
  StringListEditor,
  TextArea,
  TextInput,
} from './editing'
import { REQUIREMENT_STATUSES } from '../api'

const PRIORITIES = ['high', 'medium', 'low']
const EDITABLE = ['scope', 'summary', 'strengths', 'role_groups', 'requirements', 'recommended_skills']

const BLANK_GROUP = { label: '', count: 0, description: '', example_titles: [] }
const BLANK_REQUIREMENT = { requirement: '', frequency: '', status: 'unknown', evidence: '', gap_note: '' }
const BLANK_SKILL = { skill: '', why: '', unlocks: '', effort: '', priority: 'medium' }

function Section({ title, children }) {
  return (
    <section className="space-y-3">
      <h2>{title}</h2>
      {children}
    </section>
  )
}

/**
 * Hand-edit a stored role analysis. Claude's read of a requirement is a starting
 * point — if it marked something a gap that a project already covers, the fix
 * belongs here rather than in a re-run that costs another minute of model time.
 */
export default function RoleAnalysisEditForm({ analysis, onSave, onCancel, busy, error }) {
  const original = useMemo(
    () => Object.fromEntries(EDITABLE.map((key) => [key, analysis[key] ?? (key === 'scope' || key === 'summary' ? '' : [])])),
    [analysis],
  )
  const [draft, setDraft] = useState(original)
  const set = (patch) => setDraft((current) => ({ ...current, ...patch }))
  const dirty = JSON.stringify(draft) !== JSON.stringify(original)

  const submit = (event) => {
    event.preventDefault()
    onSave(
      Object.fromEntries(
        EDITABLE.filter((key) => JSON.stringify(draft[key]) !== JSON.stringify(original[key])).map(
          (key) => [key, draft[key]],
        ),
      ),
    )
  }

  return (
    <form onSubmit={submit} className="max-w-6xl space-y-8 pb-8">
      <p className="rounded border border-tertiary/50 bg-tertiary/10 px-3 py-2 text-tertiary">
        Editing this analysis by hand. Saving stamps it as edited; it will not match what Claude
        produced until you re-run the analysis.
      </p>
      {error ? (
        <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{error}</p>
      ) : null}

      <Section title="Overview">
        <Field label="Scope">
          <TextInput value={draft.scope} onChange={(scope) => set({ scope })} />
        </Field>
        <Field label="Summary">
          <TextArea value={draft.summary} onChange={(summary) => set({ summary })} rows={6} />
        </Field>
      </Section>

      <Section title="Your differentiating strengths">
        <StringListEditor
          values={draft.strengths}
          onChange={(strengths) => set({ strengths })}
          placeholder="Add a strength…"
          layout="rows"
        />
      </Section>

      <Section title="Role groups">
        <RowListEditor
          rows={draft.role_groups}
          onChange={(role_groups) => set({ role_groups })}
          blank={BLANK_GROUP}
          addLabel="Add role group"
          renderRow={(row, update) => (
            <div className="space-y-3">
              <div className="grid grid-cols-4 gap-3">
                <Field label="Label" className="col-span-3">
                  <TextInput value={row.label} onChange={(label) => update({ label })} />
                </Field>
                <Field label="Count">
                  <NumberInput min="0" value={row.count} onChange={(count) => update({ count: count ?? 0 })} />
                </Field>
              </div>
              <Field label="Description">
                <TextArea value={row.description} onChange={(description) => update({ description })} rows={2} />
              </Field>
              <div>
                <span className="label-data block mb-2">Example titles</span>
                <StringListEditor
                  values={row.example_titles || []}
                  onChange={(example_titles) => update({ example_titles })}
                  placeholder="Add an example title…"
                  layout="rows"
                />
              </div>
            </div>
          )}
        />
      </Section>

      <Section title="Requirement coverage">
        <RowListEditor
          rows={draft.requirements}
          onChange={(requirements) => set({ requirements })}
          blank={BLANK_REQUIREMENT}
          addLabel="Add requirement"
          renderRow={(row, update) => (
            <div className="space-y-3">
              <Field label="Requirement">
                <TextArea value={row.requirement} onChange={(requirement) => update({ requirement })} rows={2} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Status">
                  <Select
                    value={row.status}
                    onChange={(status) => update({ status: status || 'unknown' })}
                    options={REQUIREMENT_STATUSES}
                  />
                </Field>
                <Field label="How often">
                  <TextInput
                    value={row.frequency}
                    onChange={(frequency) => update({ frequency })}
                    placeholder="4 of 12 listings"
                  />
                </Field>
              </div>
              <Field label="Your evidence">
                <TextArea value={row.evidence} onChange={(evidence) => update({ evidence })} rows={2} />
              </Field>
              <Field label="Gap note">
                <TextArea value={row.gap_note} onChange={(gap_note) => update({ gap_note })} rows={2} />
              </Field>
            </div>
          )}
        />
      </Section>

      <Section title="Recommended skills">
        <RowListEditor
          rows={draft.recommended_skills}
          onChange={(recommended_skills) => set({ recommended_skills })}
          blank={BLANK_SKILL}
          addLabel="Add skill"
          renderRow={(row, update) => (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <Field label="Skill">
                  <TextInput value={row.skill} onChange={(skill) => update({ skill })} />
                </Field>
                <Field label="Priority">
                  <Select
                    value={row.priority}
                    onChange={(priority) => update({ priority: priority || 'medium' })}
                    options={PRIORITIES}
                  />
                </Field>
                <Field label="Effort">
                  <TextInput value={row.effort} onChange={(effort) => update({ effort })} placeholder="2 weekends" />
                </Field>
              </div>
              <Field label="Why it matters">
                <TextArea value={row.why} onChange={(why) => update({ why })} rows={2} />
              </Field>
              <Field label="Unlocks">
                <TextArea value={row.unlocks} onChange={(unlocks) => update({ unlocks })} rows={2} />
              </Field>
            </div>
          )}
        />
      </Section>

      <div className="sticky bottom-0 z-10 -mx-8 border-t border-outline-variant bg-surface px-8 py-3 shadow-[0_-8px_16px_-8px_rgba(0,0,0,0.6)]">
        <EditActions onCancel={onCancel} busy={busy} dirty={dirty} />
      </div>
    </form>
  )
}
