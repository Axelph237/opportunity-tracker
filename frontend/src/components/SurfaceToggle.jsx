import { useNavigate } from 'react-router-dom'
import { NavIcon } from './icons'

/**
 * Compose or Source, for the one resume you are looking at.
 *
 * The two halves of a resume live on different routes, so this navigates
 * rather than switching a local mode. Sharing the control is what makes them
 * read as one surface: it sits in the same place, looks the same, and keeps
 * the resume you had.
 *
 * A side with nothing behind it is disabled rather than hidden, because a
 * control that appears and disappears as you move down the list is harder to
 * find than one that is simply unavailable and says why.
 */
const SIDES = [
  { key: 'compose', label: 'Compose', icon: 'builder' },
  { key: 'source', label: 'Source', icon: 'resumes' },
]

export default function SurfaceToggle({ active, draftId, instanceId }) {
  const navigate = useNavigate()
  const target = { compose: draftId, source: instanceId }
  const missing = {
    compose: 'Nothing composed this. It was written as source.',
    source: 'Nothing pushed from this yet. Push it to get a document.',
  }

  return (
    <div role="tablist" aria-label="Resume surface" className="flex items-center gap-1">
      {SIDES.map(({ key, label, icon }) => {
        const to = key === 'compose' ? `/builder?draft=${draftId}` : `/resumes?instance=${instanceId}`
        const available = Boolean(target[key])
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={active === key}
            disabled={!available && active !== key}
            title={available ? label : missing[key]}
            onClick={() => active !== key && available && navigate(to)}
            className={`label-data flex items-center gap-1.5 rounded px-2 py-1 transition-colors ${
              active === key
                ? 'bg-secondary-container text-on-secondary-container'
                : available
                  ? 'hover:bg-surface-container-high hover:text-on-surface'
                  : 'opacity-40'
            }`}
          >
            <NavIcon name={icon} className="h-3.5 w-3.5" />
            {label}
          </button>
        )
      })}
    </div>
  )
}
