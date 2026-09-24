import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Dropdown from './Dropdown'
import { TexIcon } from './icons'
import { api } from '../api'

/**
 * Attaches one saved resume version to a listing.
 *
 * The list is fetched here rather than passed down because the panel can be
 * opened at any time, including right after a version was created in the
 * Resumes tab, and a stale list would silently offer the wrong choices.
 */
export default function ResumeLinkPicker({ opportunity, onChange, busy }) {
  const [instances, setInstances] = useState(null)

  useEffect(() => {
    api.resumes().then(setInstances).catch(() => setInstances([]))
  }, [])

  // Hold the row's height while loading so the panel does not jump.
  if (instances === null) return <div className="h-8" aria-hidden="true" />

  if (!instances.length) {
    return (
      <p className="text-on-surface-variant">
        <Link to="/resumes" className="text-primary underline-offset-2 hover:underline">
          Create a resume version
        </Link>{' '}
        to tailor one for this listing.
      </p>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <TexIcon className="h-4 w-4 shrink-0 text-on-surface-variant" />
      <span className="label-data">Tailored resume</span>
      <Dropdown
        ariaLabel="Resume version for this listing"
        className="w-52"
        placeholder="none"
        value={opportunity.resume_instance_id ?? ''}
        disabled={busy}
        onChange={(value) => onChange(value === undefined ? null : Number(value))}
        options={instances.map((instance) => ({
          value: instance.id,
          label: instance.is_default ? `${instance.name} (scored)` : instance.name,
        }))}
      />
      {opportunity.resume_instance_id ? (
        <Link
          to="/resumes"
          className="font-mono text-data text-on-surface-variant underline-offset-2 transition-colors hover:text-primary hover:underline"
        >
          Edit in Resumes →
        </Link>
      ) : null}
    </div>
  )
}
