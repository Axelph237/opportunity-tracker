import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import LatexIssues from '../../components/LatexIssues'
import { CheckIcon, OfflineIcon, TexIcon } from '../../components/icons'
import { api } from '../../api'
import { formatDateTime } from '../../format'

/**
 * Two slots, because they answer different questions.
 *
 * The *document* is what every listing is scored against — a PDF, or text. The
 * *source* is the LaTeX the Resumes tab edits; when one is supplied, its render
 * becomes the document, so uploading a .tex fills both at once.
 */
export default function Resume({ resume, act }) {
  const fileInput = useRef(null)
  const texInput = useRef(null)
  const [engine, setEngine] = useState(null)
  const [path, setPath] = useState('')
  const [checking, setChecking] = useState(false)
  const [engineError, setEngineError] = useState(null)
  const [fixing, setFixing] = useState(false)

  const loadEngine = () => api.latexStatus().then(setEngine).catch(() => setEngine(null))

  useEffect(() => {
    loadEngine()
  }, [])

  const upload = async (event, input) => {
    const file = event.target.files?.[0]
    if (!file) return
    await act(() => api.uploadResume(file), `Loaded ${file.name}.`)
    if (input.current) input.current.value = ''
  }

  const checkPath = async () => {
    setChecking(true)
    setEngineError(null)
    try {
      setEngine(await api.checkLatexPath(path.trim()))
      setPath('')
    } catch (err) {
      setEngineError(err.message)
    } finally {
      setChecking(false)
    }
  }

  const fixTex = async () => {
    setFixing(true)
    await act(() => api.fixResumeTex(), 'Updated resume.tex so it renders here.')
    setFixing(false)
  }

  const tex = resume?.tex

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-6 rounded border border-outline-variant bg-surface-container p-4">
          <div>
            <div className="label-data">Scored document</div>
            <div className="mt-1 font-mono text-on-surface">{resume?.filename || 'none loaded'}</div>
          </div>
          <div>
            <div className="label-data">Extracted</div>
            <div className="mt-1 font-mono text-on-surface">
              {resume?.characters ? `${resume.characters.toLocaleString()} chars` : '—'}
            </div>
          </div>
          <div>
            <div className="label-data">Updated</div>
            <div className="mt-1 font-mono text-on-surface">{formatDateTime(resume?.updated_at)}</div>
          </div>
          <div className="ml-auto">
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.txt,.md,.tex"
              onChange={(event) => upload(event, fileInput)}
              className="hidden"
              id="resume-upload"
            />
            <label htmlFor="resume-upload" className="btn btn-primary cursor-pointer">
              Upload
            </label>
          </div>
        </div>

        <p className="text-on-surface-variant">
          PDF text is extracted with pypdf and cached. Text and markdown are read as-is.
        </p>

        {!resume?.loaded ? (
          <p className="text-tertiary">No resume loaded — scores will be generic.</p>
        ) : null}
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="flex items-center gap-2">
            <TexIcon className="h-4 w-4 text-on-surface-variant" />
            LaTeX source
          </h2>
          <p className="mt-1 text-on-surface-variant">
            Upload a <span className="font-mono">.tex</span> file and the{' '}
            <Link to="/resumes" className="text-primary underline-offset-2 hover:underline">
              Resumes tab
            </Link>{' '}
            opens new versions from it. Its render replaces the scored document above, so you only
            have to keep one thing up to date.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-6 rounded border border-outline-variant bg-surface-container p-4">
          <div>
            <div className="label-data">Source</div>
            <div className="mt-1 font-mono text-on-surface">{tex?.filename || 'none uploaded'}</div>
          </div>
          <div>
            <div className="label-data">Size</div>
            <div className="mt-1 font-mono text-on-surface">
              {tex?.characters ? `${tex.characters.toLocaleString()} chars` : '—'}
            </div>
          </div>
          <div>
            <div className="label-data">Updated</div>
            <div className="mt-1 font-mono text-on-surface">{formatDateTime(tex?.updated_at)}</div>
          </div>
          <div className="ml-auto">
            <input
              ref={texInput}
              type="file"
              accept=".tex"
              onChange={(event) => upload(event, texInput)}
              className="hidden"
              id="resume-tex-upload"
            />
            <label htmlFor="resume-tex-upload" className="btn cursor-pointer">
              {tex?.present ? 'Replace .tex' : 'Upload .tex'}
            </label>
          </div>
        </div>

        {/* Checked at import, so a template that cannot render says so here
            rather than waiting to fail the first time it is opened. */}
        <LatexIssues issues={tex?.issues} onFix={fixTex} busy={fixing} />
      </section>

      <section className="space-y-3">
        <div>
          <h2>LaTeX engine</h2>
          <p className="mt-1 text-on-surface-variant">
            What renders your source to PDF. Tectonic is a single binary that fetches the packages
            it needs — a much smaller install than a full TeX distribution.
          </p>
        </div>

        {engine?.available ? (
          <div className="flex items-start gap-3 rounded border border-primary/50 bg-primary/5 px-4 py-3">
            <CheckIcon className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="text-on-surface">{engine.engine} found.</p>
              <p className="mt-1 font-mono text-data text-on-surface-variant">
                {engine.path}
                {engine.version ? ` · ${engine.version}` : ''}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3 rounded border border-tertiary/50 bg-tertiary/5 px-4 py-3">
            <div className="flex items-start gap-3">
              <OfflineIcon className="mt-0.5 h-5 w-5 shrink-0 text-tertiary" />
              <div>
                <p className="text-on-surface">No engine found on your PATH.</p>
                <p className="mt-1 text-on-surface-variant">
                  Install one with{' '}
                  <span className="font-mono text-on-surface">brew install tectonic</span>, or give
                  the full path to an existing{' '}
                  <span className="font-mono">
                    {(engine?.candidates || ['tectonic']).join(', ')}
                  </span>{' '}
                  binary. Editing and saving work without it; rendering and downloading do not.
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <input
                className="field font-mono"
                placeholder="/opt/homebrew/bin/tectonic"
                value={path}
                onChange={(event) => setPath(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    checkPath()
                  }
                }}
              />
              <button
                type="button"
                className="btn shrink-0"
                onClick={checkPath}
                disabled={checking || !path.trim()}
              >
                {checking ? 'Checking…' : 'Check'}
              </button>
            </div>
            {engineError ? <p className="text-error">{engineError}</p> : null}
          </div>
        )}
      </section>
    </div>
  )
}
