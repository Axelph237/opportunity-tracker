import { useEffect, useRef, useState } from 'react'
import LatexIssues from '../../components/LatexIssues'
import ThemeSettings from '../../components/ThemeSettings'
import { AGENT_ICON_NAMES, AgentIcon, CheckIcon, OfflineIcon, WarnIcon } from '../../components/icons'
import { api } from '../../api'
import { formatDateTime } from '../../format'

/** Step 1 — prove the CLI is reachable, or take a path from the user. */
export function ClaudeStep({ settings, reload }) {
  const [path, setPath] = useState('')
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState(null)

  const found = Boolean(settings?.claude_cli)
  const version = settings?.claude_version

  const check = async () => {
    setChecking(true)
    setError(null)
    try {
      await api.checkClaudePath(path.trim())
      await reload()
      setPath('')
    } catch (err) {
      setError(err.message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-on-surface-variant">
        Everything this app asks of Claude runs through the Claude Code CLI on this machine, using
        the login you already have. No API key is stored anywhere.
      </p>

      {found ? (
        <div className="flex items-start gap-3 rounded-lg border border-primary/50 bg-primary/5 px-4 py-3">
          <span className="mt-0.5 text-primary">
            <CheckIcon className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="text-on-surface">Claude Code found.</p>
            <p className="mt-1 font-mono text-data text-on-surface-variant">
              {settings?.claude_path} · {version}
            </p>
          </div>
        </div>
      ) : (
        <div className="space-y-3 rounded-lg border border-error/50 bg-error/5 px-4 py-3">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 text-error">
              <OfflineIcon className="h-5 w-5" />
            </span>
            <div>
              <p className="text-on-surface">Not found on your PATH.</p>
              <p className="mt-1 text-on-surface-variant">
                Enter the full path to the <span className="font-mono">claude</span> binary. Find it
                by running <span className="font-mono text-on-surface">which claude</span> in a
                terminal.
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <input
              className="field font-mono"
              placeholder="/Users/you/.local/bin/claude"
              value={path}
              onChange={(event) => setPath(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  check()
                }
              }}
            />
            <button type="button" className="btn shrink-0" onClick={check} disabled={checking || !path.trim()}>
              {checking ? 'Checking…' : 'Check'}
            </button>
          </div>
          {error ? <p className="text-error">{error}</p> : null}
        </div>
      )}

      <p className="font-mono text-data text-on-surface-variant">
        You can continue without it, but scoring, advice and the agent will not run until it is set.
      </p>
    </div>
  )
}

/** Step 2 — the Material palette, reusing the real settings panel. */
export function ThemeStep({ settings, act }) {
  return (
    <div className="space-y-4">
      <p className="text-on-surface-variant">
        Pick a colour and Material generates the whole palette from it. You can change this any time
        in Settings.
      </p>
      <ThemeSettings settings={settings} act={act} hideAgent />
    </div>
  )
}

/** Step 3 — name and icon for the in-app agent. */
export function AgentStep({ settings, act }) {
  const name = settings?.settings?.walten_name ?? 'Walten'
  const icon = settings?.settings?.walten_icon ?? 'Dog'
  const [draft, setDraft] = useState(name)

  useEffect(() => setDraft(name), [name])

  return (
    <div className="space-y-5">
      <p className="text-on-surface-variant">
        The agent lives at the bottom of the sidebar. It can tidy your data, run the scraper and —
        when you let it — change the app itself. Give it a name.
      </p>

      <div className="flex items-center gap-4 rounded-lg border border-outline-variant bg-surface-container px-4 py-3">
        <AgentIcon name={icon} className="h-8 w-8 text-primary" />
        <div className="min-w-0">
          <p className="text-on-surface">{draft || 'Walten'}</p>
          <p className="font-mono text-data text-on-surface-variant">how it appears in the sidebar</p>
        </div>
      </div>

      <label className="block space-y-1">
        <span className="label-data block">Name</span>
        <input
          className="field w-64"
          value={draft}
          placeholder="Walten"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => {
            const value = draft.trim() || 'Walten'
            if (value !== name) act(() => api.updateSettings({ walten_name: value }), null)
          }}
        />
      </label>

      <div className="space-y-2">
        <span className="label-data block">Icon</span>
        <div className="flex flex-wrap gap-1">
          {AGENT_ICON_NAMES.map((option) => (
            <button
              key={option}
              type="button"
              title={option}
              aria-label={option}
              aria-pressed={option === icon}
              onClick={() => option !== icon && act(() => api.updateSettings({ walten_icon: option }), null)}
              className={`rounded border p-2 transition-colors ${
                option === icon
                  ? 'border-primary bg-secondary-container text-on-secondary-container'
                  : 'border-transparent text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
              }`}
            >
              <AgentIcon name={option} />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

/** Step 4 — the document every listing is scored against, and its LaTeX source. */
export function ResumeStep({ settings, resume, act }) {
  const fileInput = useRef(null)
  const texInput = useRef(null)
  const [busy, setBusy] = useState(false)

  const upload = async (event, input) => {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy(true)
    await act(() => api.uploadResume(file), null)
    setBusy(false)
    if (input.current) input.current.value = ''
  }

  const tex = resume?.tex

  return (
    <div className="space-y-5">
      <p className="text-on-surface-variant">
        Every listing is scored against this document, and it is what the resume advice compares to.
        PDF, text or markdown.
      </p>

      {resume?.loaded ? (
        <div className="flex items-start gap-3 rounded-lg border border-primary/50 bg-primary/5 px-4 py-3">
          <span className="mt-0.5 text-primary">
            <CheckIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="font-mono text-on-surface">{resume.filename}</p>
            <p className="mt-1 font-mono text-data text-on-surface-variant">
              {resume.characters?.toLocaleString()} characters · {formatDateTime(resume.updated_at)}
            </p>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3 rounded-lg border border-tertiary/50 bg-tertiary/5 px-4 py-3">
          <span className="mt-0.5 text-tertiary">
            <WarnIcon className="h-5 w-5" />
          </span>
          <p className="text-on-surface-variant">
            No resume yet. Scraping still works, but every score will be generic.
          </p>
        </div>
      )}

      <input
        ref={fileInput}
        type="file"
        accept=".pdf,.txt,.md,.tex"
        onChange={(event) => upload(event, fileInput)}
        className="hidden"
        id="onboarding-resume"
      />
      <label htmlFor="onboarding-resume" className="btn btn-primary cursor-pointer">
        {busy ? 'Reading…' : resume?.loaded ? 'Replace resume' : 'Upload resume'}
      </label>

      {/* Optional, and deliberately second: the app works fully without it.
          Supplying it is what makes the Resumes tab open on the user's own
          document rather than a template. */}
      <div className="space-y-3 border-t border-outline-variant pt-5">
        <div>
          <p className="text-on-surface">Have the LaTeX source too?</p>
          <p className="mt-1 text-on-surface-variant">
            Upload the <span className="font-mono">.tex</span> and the Resumes tab can edit your
            real resume, render it and tailor a version per listing. Optional — you can add it
            later in Settings.
          </p>
        </div>

        {tex?.present ? (
          <div className="flex items-start gap-3 rounded-lg border border-primary/50 bg-primary/5 px-4 py-3">
            <span className="mt-0.5 text-primary">
              <CheckIcon className="h-5 w-5" />
            </span>
            <div>
              <p className="font-mono text-on-surface">{tex.filename}</p>
              <p className="mt-1 font-mono text-data text-on-surface-variant">
                {tex.characters?.toLocaleString()} characters · {formatDateTime(tex.updated_at)}
              </p>
            </div>
          </div>
        ) : null}

        <input
          ref={texInput}
          type="file"
          accept=".tex"
          onChange={(event) => upload(event, texInput)}
          className="hidden"
          id="onboarding-resume-tex"
        />
        <label htmlFor="onboarding-resume-tex" className="btn cursor-pointer">
          {tex?.present ? 'Replace .tex' : 'Upload .tex'}
        </label>

        {/* Most real resumes come from a template written for pdflatex. Say so
            now, with the repair, rather than at the first failed render. */}
        <LatexIssues
          issues={tex?.issues}
          busy={busy}
          onFix={async () => {
            setBusy(true)
            await act(() => api.fixResumeTex(), null)
            setBusy(false)
          }}
        />
      </div>
    </div>
  )
}
