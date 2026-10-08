import { useEffect, useState } from 'react'
import { Field, TextInput } from '../../components/editing'
import { api } from '../../api'

/**
 * How a slot is written in a resume's source.
 *
 * The default is a pair of LaTeX comments, so a document carrying them still
 * compiles anywhere with nothing installed. Anyone who would rather use an
 * environment or a macro of their own can say so here, which is why the shape
 * is a setting rather than a constant.
 */
export default function SlotMarkers({ act }) {
  const [form, setForm] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.slotMarkers().then(setForm).catch((err) => setError(err.message))
  }, [])

  if (!form) {
    return <p className="font-mono text-data text-on-surface-variant">{error || 'Loading…'}</p>
  }

  const save = async () => {
    setError(null)
    try {
      setForm(await api.saveSlotMarkers(form))
      await act(async () => {}, 'Slot markers saved.')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-on-surface-variant">
        A slot is a named stretch of a resume's source that the composer may rearrange. Everything
        outside every slot is yours, and nothing here will ever rewrite it.
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Opening marker" hint="Needs {name}, which is where the slot's name goes.">
          <TextInput value={form.open} onChange={(open) => setForm({ ...form, open })} />
        </Field>
        <Field label="Closing marker">
          <TextInput value={form.close} onChange={(close) => setForm({ ...form, close })} />
        </Field>
      </div>

      <div className="rounded border border-outline-variant bg-surface-container p-3">
        <div className="label-data">How that reads in a document</div>
        <pre className="mt-2 overflow-x-auto font-code text-data text-on-surface-variant">
{`${(form.open || '').replace('{name}', 'experience')}
\\resumeSubheading{UChicago PME}{Jun 2025 -- Present}{Research Assistant}{Chicago, IL}
${form.close || ''}`}
        </pre>
      </div>

      {error ? <p className="text-error">{error}</p> : null}

      <button type="button" className="btn btn-primary" onClick={save}>
        Save markers
      </button>
    </div>
  )
}
