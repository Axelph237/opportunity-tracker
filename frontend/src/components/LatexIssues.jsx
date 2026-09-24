import { useState } from 'react'
import { ChevronIcon, WarnIcon } from './icons'

/**
 * Known reasons a document will not compile here, with the repair offered.
 *
 * Deliberately not applied automatically. The editor has to show the document
 * that will actually be rendered, and a template silently rewritten on the way
 * to the engine is a source of confusion far worse than the error it avoids.
 */
export default function LatexIssues({ issues, onFix, busy, onGoToLine }) {
  const [open, setOpen] = useState(false)
  if (!issues?.length) return null

  const count = issues.length

  return (
    <div className="rounded border border-tertiary/60 bg-tertiary/10 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <WarnIcon className="h-4 w-4 shrink-0 text-tertiary" />
        <p className="min-w-0 flex-1 text-on-surface-variant">
          This template uses {count} command{count === 1 ? '' : 's'} that only pdflatex
          understands, so it will not render here as written.
        </p>
        <button type="button" className="btn btn-primary shrink-0" onClick={onFix} disabled={busy}>
          {busy ? 'Fixing…' : count === 1 ? 'Fix it' : 'Fix them'}
        </button>
        <button
          type="button"
          onClick={() => setOpen((shown) => !shown)}
          aria-expanded={open}
          className="flex shrink-0 items-center gap-1 font-mono text-data text-on-surface-variant underline-offset-2 transition-colors hover:text-on-surface"
        >
          <ChevronIcon className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`} />
          {open ? 'Hide' : 'What changes'}
        </button>
      </div>

      {open ? (
        <ul className="mt-2 space-y-2 border-t border-tertiary/30 pt-2">
          {issues.map((issue, index) => (
            <li key={`${issue.id}-${index}`}>
              <div className="flex items-baseline gap-2">
                {onGoToLine ? (
                  <button
                    type="button"
                    onClick={() => onGoToLine(issue.line)}
                    title="Jump to this line"
                    className="font-mono text-data text-on-surface-variant transition-colors hover:text-primary"
                  >
                    line {issue.line}
                  </button>
                ) : (
                  <span className="font-mono text-data text-on-surface-variant">
                    line {issue.line}
                  </span>
                )}
                <span className="text-on-surface">{issue.title}</span>
              </div>
              <p className="mt-0.5 font-code text-data text-on-surface-variant">{issue.snippet}</p>
              <p className="mt-0.5 text-on-surface-variant">{issue.detail}</p>
            </li>
          ))}
          <li className="text-on-surface-variant">
            Each line is wrapped in <span className="font-code">\ifdefined…\fi</span> rather than
            deleted, so the document still behaves the same way if you compile it with pdflatex
            somewhere else.
          </li>
        </ul>
      ) : null}
    </div>
  )
}
