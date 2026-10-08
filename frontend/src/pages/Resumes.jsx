import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import LatexEditor from '../components/LatexEditor'
import LatexIssues from '../components/LatexIssues'
import PageLayout from '../components/PageLayout'
import PdfPreview from '../components/PdfPreview'
import ResumeLibraryRail from '../components/ResumeLibraryRail'
import SurfaceToggle from '../components/SurfaceToggle'
import ResumeAssets from '../components/ResumeAssets'
import ResumeRecommendations from '../components/ResumeRecommendations'
import { ResizeHandle, usePanelSize } from '../components/Resizable'
import { useConfirm } from '../components/ConfirmDialog'
import {
  CheckIcon,
  DownloadIcon,
  DuplicateIcon,
  NavIcon,
  PlusIcon,
  SidebarIcon,
  StarIcon,
  TrashIcon,
  WarnIcon,
} from '../components/icons'
import { api } from '../api'
import { formatDateTime, relativeTime } from '../format'

// Long enough that a burst of typing is one compile, short enough that pausing
// to think gets you a fresh preview. Tectonic takes roughly a second on a resume.
const AUTOSAVE_MS = 700
const COMPILE_MS = 1400

function SaveState({ saving, dirty, savedAt }) {
  if (saving) return <span className="font-mono text-data text-on-surface-variant">Saving…</span>
  if (dirty) return <span className="font-mono text-data text-on-surface-variant">Unsaved</span>
  if (savedAt) {
    return (
      <span className="font-mono text-data text-on-surface-variant" title={formatDateTime(savedAt)}>
        Saved {relativeTime(savedAt)}
      </span>
    )
  }
  return null
}


/**
 * Which resume the editor should open.
 *
 * Only a row with a document behind it can be opened here, so a draft nobody
 * has pushed is skipped rather than selected into an empty editor.
 */
function firstOpenable(rows, asked) {
  const openable = rows.filter((row) => row.pushed)
  if (openable.some((row) => row.instance_id === asked)) return asked
  return openable.find((row) => row.is_default)?.instance_id ?? openable[0]?.instance_id ?? null
}

export default function Resumes({ onMutate }) {
  // Every resume, composed or written. The editor can only open the ones
  // with a document behind them; the rest link to the canvas.
  const [instances, setInstances] = useState([])
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState(null)
  const [instance, setInstance] = useState(null)
  const [source, setSource] = useState('')
  const [links, setLinks] = useState([])
  const [linksLoading, setLinksLoading] = useState(false)
  const [engine, setEngine] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [compiling, setCompiling] = useState(false)
  const [busy, setBusy] = useState(false)
  const [showRail, setShowRail] = useState(true)
  const [showLog, setShowLog] = useState(false)
  const [error, setError] = useState(null)
  const editor = useRef(null)
  const confirm = useConfirm()

  // Bumped after every compile so the browser refetches the preview instead of
  // showing the render from before the edit.
  const [pdfVersion, setPdfVersion] = useState(0)

  // Every divider on this page is draggable and remembered. The minimums are
  // the point at which a pane stops being usable rather than merely small: a
  // rail too narrow to read a version name is worse than no rail.
  const [railWidth, setRailWidth, resetRail] = usePanelSize('resumes.rail', 224, {
    min: 160,
    max: 420,
  })
  const [assetsHeight, setAssetsHeight, resetAssets] = usePanelSize('resumes.assets', 200, {
    min: 90,
    max: 600,
  })
  const [editorWidth, setEditorWidth, resetEditor] = usePanelSize('resumes.editor', 560, {
    min: 280,
    max: 1400,
  })
  const [adviceWidth, setAdviceWidth, resetAdvice] = usePanelSize('resumes.advice', 320, {
    min: 240,
    max: 560,
  })

  const refreshList = useCallback(async () => {
    const rows = await api.resumeLibrary()
    setInstances(rows)
    return rows
  }, [])

  // First load: fetch the variants and open the default one.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [rows, engineStatus] = await Promise.all([api.resumeLibrary(), api.latexStatus()])
        if (cancelled) return
        setInstances(rows)
        setEngine(engineStatus)
        // Arriving from the Builder opens the resume it just pushed, rather
        // than the scored one.
        setSelectedId(firstOpenable(rows, Number(params.get('instance'))))
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Load the selected variant's document and the listings using it.
  useEffect(() => {
    if (!selectedId) {
      setInstance(null)
      setSource('')
      setLinks([])
      return undefined
    }
    let cancelled = false
    setLinksLoading(true)
    ;(async () => {
      try {
        const [detail, linked] = await Promise.all([
          api.resumeInstance(selectedId),
          api.resumeLinks(selectedId),
        ])
        if (cancelled) return
        // Every setter in one pass, `linksLoading` included: a `finally` block
        // would land it in a second render, which shows the empty-rail message
        // for a frame before the rail it was waiting on appears.
        setInstance(detail)
        setSource(detail.latex)
        setLinks(linked)
        setDirty(false)
        setError(null)
        setLinksLoading(false)
      } catch (err) {
        if (cancelled) return
        setError(err.message)
        setLinksLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedId])

  // Autosave, then compile once the typing has actually stopped. Two timers
  // rather than one: the document should be safe on disk well before the far
  // more expensive render is worth starting.
  useEffect(() => {
    if (!instance || !dirty) return undefined
    const timer = setTimeout(async () => {
      setSaving(true)
      try {
        const saved = await api.updateResumeInstance(instance.id, { latex: source })
        setInstance((current) => (current?.id === saved.id ? { ...current, ...saved } : current))
        setDirty(false)
        setError(null)
      } catch (err) {
        setError(err.message)
      } finally {
        setSaving(false)
      }
    }, AUTOSAVE_MS)
    return () => clearTimeout(timer)
  }, [source, dirty, instance])

  const compile = useCallback(
    async (id) => {
      if (!id) return
      setCompiling(true)
      try {
        const compiled = await api.compileResumeInstance(id)
        setInstance((current) => (current?.id === compiled.id ? { ...current, ...compiled } : current))
        setPdfVersion((version) => version + 1)
        setError(null)
        await refreshList()
      } catch (err) {
        setError(err.message)
      } finally {
        setCompiling(false)
      }
    },
    [refreshList],
  )

  // Recompile a little after the save settles.
  useEffect(() => {
    if (!instance || dirty || saving || !engine?.available) return undefined
    const timer = setTimeout(() => compile(instance.id), COMPILE_MS)
    return () => clearTimeout(timer)
    // `source` is the trigger: a save that changed nothing should not rebuild.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, dirty, saving, engine?.available])

  const act = async (fn) => {
    setBusy(true)
    try {
      await fn()
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const create = (copyFrom) =>
    act(async () => {
      const name = copyFrom ? `${instance?.name} copy` : 'New resume'
      const created = await api.createResumeInstance(
        copyFrom ? { name, copy_from: copyFrom } : { name },
      )
      await refreshList()
      setSelectedId(created.id)
      onMutate?.()
    })

  /**
   * Cut this resume loose from the canvas so its source can be hand-edited.
   *
   * Composing is lossy one way: LaTeX cannot be read back into bank records.
   * Rather than let the two fight, which is what the refused push was, the
   * choice is made once here and nothing is thrown away on either side.
   */
  const detach = async () => {
    const confirmed = await confirm({
      title: 'Edit this source by hand?',
      body: (
        <>
          <p>
            This resume is composed on the canvas, and every push rewrites its source. Detaching
            stops that so you can edit it here.
          </p>
          <p className="mt-2 text-on-surface-variant">
            Nothing is deleted. The canvas version stays as its own resume, still composed from
            your bank, and this document carries on without it.
          </p>
        </>
      ),
      confirmLabel: 'Detach and edit',
    })
    if (!confirmed) return
    act(async () => {
      await api.detachDraft(instance.draft_id)
      setInstance(await api.resumeInstance(instance.id))
      await refreshList()
    })
  }

  /**
   * Open a row from the shared rail.
   *
   * A draft nobody has pushed has no document for this surface to show, so it
   * opens on the canvas instead. The rail is the same on both; only what a
   * row means differs.
   */
  const openRow = (row) => {
    if (row.pushed) setSelectedId(row.instance_id)
    else navigate(`/builder?draft=${row.draft_id}`)
  }

  const rename = (name) => {
    if (!instance || name === instance.name) return
    act(async () => {
      const saved = await api.updateResumeInstance(instance.id, { name })
      setInstance((current) => ({ ...current, ...saved }))
      await refreshList()
    })
  }

  const makeDefault = () =>
    act(async () => {
      const saved = await api.makeResumeDefault(instance.id)
      setInstance((current) => ({ ...current, ...saved }))
      await refreshList()
    })

  const fixIssues = () =>
    act(async () => {
      const fixed = await api.fixResumeInstance(instance.id)
      setInstance((current) => ({ ...current, ...fixed }))
      // The editor is the source of truth for what gets saved next, so it has
      // to pick up the rewrite rather than keep the version that broke.
      setSource(fixed.latex)
      setDirty(false)
    })

  const remove = async () => {
    if (!instance) return
    const confirmed = await confirm({
      key: 'delete-resume',
      title: 'Delete this resume?',
      body: (
        <>
          <span className="text-on-surface">{instance.name}</span> and its rendered PDF go for good.
          {instance.linked_count
            ? ` ${instance.linked_count} listing${
                instance.linked_count === 1 ? '' : 's'
              } will be unlinked, but nothing else about them changes.`
            : ''}
        </>
      ),
      confirmLabel: 'Delete resume',
    })
    if (!confirmed) return
    act(async () => {
      await api.deleteResumeInstance(instance.id)
      const rows = await refreshList()
      setSelectedId(firstOpenable(rows))
      onMutate?.()
    })
  }

  const errorLines = useMemo(
    () => (instance?.compile_errors || []).map((item) => item.line).filter(Boolean),
    [instance?.compile_errors],
  )

  const compileErrors = instance?.compile_ok ? [] : instance?.compile_errors || []

  const pdfUrl = instance?.has_pdf
    ? api.resumePdfUrl(instance.id, { version: `${instance.compiled_at || ''}-${pdfVersion}` })
    : null

  if (loading) {
    return (
      <PageLayout
        title="Resumes"
        icon="resumes"
        description="Tailored versions of your resume, written in LaTeX."
      >
        <p className="py-6 font-mono text-data text-on-surface-variant">Loading…</p>
      </PageLayout>
    )
  }

  return (
    <PageLayout
      title="Resumes"
      icon="resumes"
      description="The document itself, in LaTeX, rendered beside what you are writing."
      error={error}
      scroll={false}
      padded={false}
      banner={
        engine && !engine.available ? (
          <div className="mb-4 flex items-start gap-3 rounded border border-tertiary/60 bg-tertiary/10 px-4 py-2.5">
            <WarnIcon className="mt-0.5 h-4 w-4 shrink-0 text-tertiary" />
            <p className="text-on-surface-variant">
              No LaTeX engine installed, so nothing can be rendered or downloaded yet. Install one
              with <span className="font-mono text-on-surface">brew install tectonic</span>, or
              point the app at an existing binary in{' '}
              <Link to="/settings/resume" className="text-primary underline-offset-2 hover:underline">
                Settings → Resume
              </Link>
              . You can still write and save your source.
            </p>
          </div>
        ) : instance?.draft_id ? (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded border border-primary/50 bg-primary/5 px-4 py-2.5">
            <NavIcon name="builder" className="h-4 w-4 shrink-0 text-primary" />
            <p className="min-w-0 flex-1 text-on-surface-variant">
              Composed on the canvas. Every push rewrites this source, so it is read-only here
              until you detach it.
            </p>
            <Link to={`/builder?draft=${instance.draft_id}`} className="btn">
              Open in Builder
            </Link>
            <button type="button" className="btn" onClick={detach} disabled={busy}>
              Detach and edit
            </button>
          </div>
        ) : null
      }
      actions={
        instance ? (
          <>
            <SurfaceToggle active="source" draftId={instance.draft_id} instanceId={instance.id} />
            <SaveState saving={saving} dirty={dirty} savedAt={instance.updated_at} />
            <button
              type="button"
              className="btn"
              onClick={() => compile(instance.id)}
              disabled={compiling || !engine?.available}
              title={engine?.available ? 'Render this resume now' : 'No LaTeX engine installed'}
            >
              {compiling ? 'Rendering…' : 'Render'}
            </button>
            <a
              href={instance.has_pdf ? api.resumePdfUrl(instance.id, { download: true }) : undefined}
              aria-disabled={!instance.has_pdf}
              className={`btn ${instance.has_pdf ? '' : 'pointer-events-none opacity-45'}`}
              title={instance.has_pdf ? 'Download the rendered PDF' : 'Render it first'}
            >
              <DownloadIcon />
              PDF
            </a>
            <button
              type="button"
              className="btn"
              onClick={() => setShowRail((open) => !open)}
              aria-pressed={showRail}
              title={showRail ? 'Hide recommendations' : 'Show recommendations'}
            >
              <SidebarIcon />
              {links.length ? `Advice (${links.length})` : 'Advice'}
            </button>
          </>
        ) : null
      }
    >
      <div className="flex h-full min-h-0">
        {/* Versions above, assets below, with their own draggable divider. */}
        <div className="flex h-full min-h-0 shrink-0 flex-col" style={{ width: railWidth }}>
          <div className="min-h-0 flex-1">
            <ResumeLibraryRail
              rows={instances}
              selectedKey={selectedId ? `instance:${selectedId}` : null}
              onSelect={openRow}
              onCreate={() => create(null)}
              busy={busy}
            />
          </div>
          <ResizeHandle
            orientation="horizontal"
            label="Resize the assets panel"
            value={assetsHeight}
            onChange={setAssetsHeight}
            onReset={resetAssets}
            min={90}
            max={600}
            invert
          />
          <div className="shrink-0" style={{ height: assetsHeight }}>
            <ResumeAssets
              onInsert={(text) => editor.current?.insertAtCursor(text)}
              // A new image changes what the document can resolve, so the
              // render on screen is out of date the moment one lands.
              onChanged={() => instance && engine?.available && compile(instance.id)}
            />
          </div>
        </div>

        <ResizeHandle
          orientation="vertical"
          label="Resize the versions rail"
          value={railWidth}
          onChange={setRailWidth}
          onReset={resetRail}
          min={160}
          max={420}
        />

        {!instance ? (
          <div className="flex flex-1 items-center justify-center p-10 text-center">
            <div className="max-w-md space-y-3">
              <p className="text-on-surface-variant">
                {instances.length ? (
                  <>
                    Nothing here has been pushed into a document yet. Open one on the canvas and
                    push it, or write a new one from source.
                  </>
                ) : (
                  <>
                    No resumes yet. Create one to start from your uploaded{' '}
                    <span className="font-mono">resume.tex</span>, or from a template if you have
                    not uploaded one.
                  </>
                )}
              </p>
              <button type="button" className="btn btn-primary" onClick={() => create(null)} disabled={busy}>
                <PlusIcon />
                New resume
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex min-w-0 shrink-0 flex-col" style={{ width: editorWidth }}>
              <div className="flex flex-wrap items-center gap-2 border-b border-outline-variant px-3 py-2">
                <input
                  key={instance.id}
                  className="field max-w-[16rem] flex-1"
                  defaultValue={instance.name}
                  aria-label="Resume name"
                  onBlur={(event) => rename(event.target.value.trim())}
                  onKeyDown={(event) => event.key === 'Enter' && event.target.blur()}
                />
                {instance.is_default ? (
                  <span
                    className="inline-flex items-center gap-1 rounded border border-primary/60 bg-primary/10 px-2 py-[2px] font-mono text-data text-primary"
                    title="Every listing is scored against this version"
                  >
                    <StarIcon className="h-3 w-3" />
                    scored
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn"
                    onClick={makeDefault}
                    disabled={busy}
                    title="Score every listing against this version from now on"
                  >
                    <CheckIcon />
                    Use for scoring
                  </button>
                )}
                <button
                  type="button"
                  className="btn"
                  onClick={() => create(instance.id)}
                  disabled={busy}
                  title="Copy this version into a new one"
                >
                  <DuplicateIcon />
                  Duplicate
                </button>
                <button
                  type="button"
                  className="btn ml-auto hover:border-error hover:text-error"
                  onClick={remove}
                  disabled={busy}
                >
                  <TrashIcon />
                  Delete
                </button>
              </div>

              {instance.issues?.length ? (
                <div className="border-b border-outline-variant p-3">
                  <LatexIssues
                    issues={instance.issues}
                    onFix={fixIssues}
                    busy={busy}
                    onGoToLine={(line) => editor.current?.goToLine(line)}
                  />
                </div>
              ) : null}

              <div className="min-h-0 flex-1">
                <LatexEditor
                  key={instance.id}
                  editorRef={editor}
                  value={source}
                  errorLines={errorLines}
                  // A composed resume is rewritten from the canvas on every
                  // push, so an edit here is lost work until it is detached.
                  readOnly={Boolean(instance.draft_id)}
                  onChange={(next) => {
                    setSource(next)
                    setDirty(true)
                  }}
                />
              </div>

              {compileErrors.length ? (
                <div className="max-h-44 shrink-0 overflow-y-auto border-t border-error/50 bg-error/5">
                  <div className="flex items-center justify-between gap-2 px-3 py-1.5">
                    <span className="label-data text-error">
                      {compileErrors.length} compile error{compileErrors.length === 1 ? '' : 's'}
                    </span>
                    <button
                      type="button"
                      className="font-mono text-data text-on-surface-variant underline-offset-2 hover:text-on-surface hover:underline"
                      onClick={() => setShowLog((open) => !open)}
                    >
                      {showLog ? 'Hide full log' : 'Full log'}
                    </button>
                  </div>
                  <ul className="px-3 pb-2">
                    {compileErrors.map((item, index) => (
                      <li key={index}>
                        <button
                          type="button"
                          onClick={() => editor.current?.goToLine(item.line)}
                          disabled={!item.line}
                          className="w-full text-left font-mono text-data text-on-surface-variant transition-colors hover:text-error disabled:cursor-default"
                        >
                          {item.line ? `line ${item.line}: ` : ''}
                          {item.message}
                        </button>
                      </li>
                    ))}
                  </ul>
                  {showLog ? (
                    <pre className="overflow-x-auto border-t border-outline-variant px-3 py-2 font-code text-data text-on-surface-variant">
                      {instance.compile_log || 'No log recorded.'}
                    </pre>
                  ) : null}
                </div>
              ) : null}
            </div>

            <ResizeHandle
              orientation="vertical"
              label="Resize the editor"
              value={editorWidth}
              onChange={setEditorWidth}
              onReset={resetEditor}
              min={280}
              max={1400}
            />

            <div className="hidden min-w-0 flex-1 flex-col bg-surface-container-lowest lg:flex">
              {pdfUrl ? (
                <PdfPreview url={pdfUrl} label={`${instance.name} preview`} />
              ) : (
                <div className="flex h-full items-center justify-center p-6 text-center text-on-surface-variant">
                  {compiling
                    ? 'Rendering…'
                    : engine?.available
                      ? 'No render yet. Press Render, or just start typing.'
                      : 'Install a LaTeX engine to see the rendered PDF.'}
                </div>
              )}
            </div>

            {showRail ? (
              <>
                <ResizeHandle
                  orientation="vertical"
                  label="Resize the recommendations rail"
                  value={adviceWidth}
                  onChange={setAdviceWidth}
                  onReset={resetAdvice}
                  min={240}
                  max={560}
                  invert
                />
                <aside
                  className="flex shrink-0 flex-col bg-surface-container"
                  style={{ width: adviceWidth }}
                >
                  <div className="border-b border-outline-variant px-4 py-2">
                    <span className="label-data">Recommendations</span>
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    <ResumeRecommendations
                      instanceId={instance.id}
                      links={links}
                      loading={linksLoading}
                      onInsert={(text) => editor.current?.insertAtCursor(text)}
                    />
                  </div>
                </aside>
              </>
            ) : null}
          </>
        )}
      </div>
    </PageLayout>
  )
}
