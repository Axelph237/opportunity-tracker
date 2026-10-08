import { useState } from 'react'
import { EditActions, Field, TextInput } from './editing'
import { PlusIcon, TrashIcon } from './icons'

const BLANK = { name: '', location: '', email: '', phone: '', links: [] }

const formOf = (contact) => ({
  ...BLANK,
  ...Object.fromEntries(Object.keys(BLANK).map((key) => [key, contact?.[key] ?? BLANK[key]])),
  links: (contact?.links || []).map((link) => ({ label: link.label || '', url: link.url || '' })),
})

/**
 * The block printed above the first section: who this resume is for.
 *
 * One record for the whole app rather than one per draft, which the copy says
 * out loud. A name does not change with the job, and asking for it on every
 * new resume is how one goes out still reading "Your Name".
 */
export default function ContactForm({ contact, onSave, onCancel, busy }) {
  const [form, setForm] = useState(() => formOf(contact))
  const set = (patch) => setForm((current) => ({ ...current, ...patch }))

  const setLink = (index, patch) =>
    setForm((current) => ({
      ...current,
      links: current.links.map((link, i) => (i === index ? { ...link, ...patch } : link)),
    }))

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        // A link with no address prints as nothing, so it is dropped here
        // rather than stored and filtered again on the way out.
        onSave({ ...form, links: form.links.filter((link) => link.url.trim()) })
      }}
    >
      <p className="text-on-surface-variant">
        This heads every resume you build, so it is stored once rather than per resume.
      </p>

      <Field label="Name">
        <TextInput value={form.name} onChange={(name) => set({ name })} placeholder="Aiden King" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Email">
          <TextInput value={form.email} onChange={(email) => set({ email })} placeholder="you@uchicago.edu" />
        </Field>
        <Field label="Phone">
          <TextInput value={form.phone} onChange={(phone) => set({ phone })} placeholder="(312) 555-0100" />
        </Field>
      </div>
      <Field label="Location" hint="City and state is the convention; a street address is not.">
        <TextInput value={form.location} onChange={(location) => set({ location })} placeholder="Chicago, IL" />
      </Field>

      <div className="space-y-2">
        <span className="label-data block">Links</span>
        {form.links.length ? (
          <ul className="space-y-2">
            {form.links.map((link, index) => (
              <li key={index} className="flex items-start gap-2">
                <TextInput
                  value={link.label}
                  onChange={(label) => setLink(index, { label })}
                  placeholder="github.com/me"
                  aria-label={`Link ${index + 1} text`}
                  className="w-1/3"
                />
                <TextInput
                  value={link.url}
                  onChange={(url) => setLink(index, { url })}
                  placeholder="https://github.com/me"
                  aria-label={`Link ${index + 1} address`}
                  className="flex-1"
                />
                <button
                  type="button"
                  aria-label={`Remove link ${index + 1}`}
                  className="mt-2 shrink-0 text-on-surface-variant transition-colors hover:text-error"
                  onClick={() => set({ links: form.links.filter((_, i) => i !== index) })}
                >
                  <TrashIcon />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="font-mono text-data text-on-surface-variant">
            No links yet. A repository and a profile are the two worth printing.
          </p>
        )}
        <button
          type="button"
          className="btn"
          onClick={() => set({ links: [...form.links, { label: '', url: '' }] })}
        >
          <PlusIcon />
          Add a link
        </button>
      </div>

      <EditActions onCancel={onCancel} busy={busy} saveLabel="Save contact details" />
    </form>
  )
}
