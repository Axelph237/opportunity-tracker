import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import BankEntryForm from '../components/BankEntryForm'
import BankRail from '../components/BankRail'
import ContactForm from '../components/ContactForm'
import CoveragePanel, { JobAdForm } from '../components/CoveragePanel'
import Dropdown from '../components/Dropdown'
import PageLayout from '../components/PageLayout'
import ProposalReview from '../components/ProposalReview'
import SlotCanvas from '../components/SlotCanvas'
import SurfaceToggle from '../components/SurfaceToggle'
import SlidePanel from '../components/SlidePanel'
import { ResizeHandle, usePanelSize } from '../components/Resizable'
import { useConfirm } from '../components/ConfirmDialog'
import { EditIcon, PlusIcon } from '../components/icons'
import { api } from '../api'

const BANK_WIDTH = { default: 240, min: 180, max: 420 }
const COVERAGE_WIDTH = { default: 300, min: 240, max: 560 }

/**
 * Bring the bank's bullets in line with what the form handed back.
 *
 * Bullets are child rows with their own endpoints, so one Save on the form
 * becomes a create, a patch or a delete per bullet that actually changed.
 */
async function syncBullets(entryId, before, after) {
  const was = new Map(before.map((bullet) => [bullet.id, bullet.text]))
  for (const bullet of after) {
    if (bullet.id == null) await api.createBankBullet(entryId, { text: bullet.text })
    else if (was.get(bullet.id) !== bullet.text) await api.updateBankBullet(bullet.id, { text: bullet.text })
  }
  const kept = new Set(after.map((bullet) => bullet.id))
  for (const bullet of before) {
    if (!kept.has(bullet.id)) await api.deleteBankBullet(bullet.id)
  }
}

/** Confirm what Claude read out of the resume before any of it is written. */
function ImportPreview({ preview, busy, onConfirm, onCancel }) {
  const entries = preview?.entries || []
  const [rejected, setRejected] = useState(() => new Set())
  const chosen = entries.filter((_, index) => !rejected.has(index))

  const toggle = (index) =>
    setRejected((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })

  if (!entries.length) {
    return (
      <div className="space-y-3">
        <p className="text-on-surface-variant">
          Claude found nothing it could turn into bank records. Upload a resume under Settings →
          Resume, or add the first record by hand.
        </p>
        <button type="button" className="btn" onClick={onCancel}>
          Close
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-on-surface-variant">
        Nothing is saved until you say so. Untick anything that came out wrong — you can fix the
        wording after it lands.
      </p>
      <ul className="space-y-2">
        {entries.map((entry, index) => (
          <li key={index} className="rounded border border-outline-variant bg-surface p-3">
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 shrink-0 accent-primary"
                checked={!rejected.has(index)}
                onChange={() => toggle(index)}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-on-surface">{entry.title}</span>
                <span className="block font-mono text-data text-on-surface-variant">
                  {[entry.kind, entry.organization].filter(Boolean).join(' · ')}
                </span>
                {entry.bullets?.length ? (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-on-surface-variant marker:text-primary">
                    {entry.bullets.map((bullet, position) => (
                      <li key={position}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-3 border-t border-outline-variant pt-4">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || !chosen.length}
          onClick={() => onConfirm(chosen)}
        >
          {busy ? 'Adding…' : `Add ${chosen.length} to my bank`}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          Discard
        </button>
      </div>
    </div>
  )
}

/**
 * Compose a resume for one job ad out of the experience bank.
 *
 * Three panes: what you have on the left, what you are writing in the middle,
 * what the ad asked for on the right. The coverage panel refreshes on every
 * edit rather than behind a button, because watching a missing keyword go
 * covered as you drag a bullet in is the point of the whole page.
 */
export default function Builder() {
  const [instanceId, setInstanceId] = useState(null)
  const [instance, setInstance] = useState(null)
  const [bank, setBank] = useState([])
  const [jobPost, setJobPost] = useState(null)
  const [coverage, setCoverage] = useState([])
  const [proposal, setProposal] = useState(null)
  const [standing, setStanding] = useState(null)
  // Every resume, so the switcher here offers the same set the Resumes
  // rail does rather than only the ones this surface can compose.
  const [library, setLibrary] = useState([])
  const [importPreview, setImportPreview] = useState(null)
  const [contact, setContact] = useState(null)
  const [editingContact, setEditingContact] = useState(false)
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState(false)
  const [rendering, setRendering] = useState(false)
  const [rendered, setRendered] = useState(null)
  // The document's own regions, once it has any. A resume with slots is
  const [docSlots, setDocSlots] = useState(null)
  const [slotError, setSlotError] = useState(null)
  // Escape unmounts the field, and the blur it fires must not commit.
  const cancelRename = useRef(false)
  const [editingAd, setEditingAd] = useState(false)
  const [editing, setEditing] = useState(null)
  const [draggingEntry, setDraggingEntry] = useState(null)
  const [focusedPlacement, setFocusedPlacement] = useState(null)

  const [loading, setLoading] = useState(true)
  const [coverageLoading, setCoverageLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [importing, setImporting] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  const [bankWidth, setBankWidth, resetBank] = usePanelSize('builder.bank', BANK_WIDTH.default, BANK_WIDTH)
  const [coverageWidth, setCoverageWidth, resetCoverage] = usePanelSize(
    'builder.coverage',
    COVERAGE_WIDTH.default,
    COVERAGE_WIDTH,
  )
  const confirm = useConfirm()

  const reloadBank = useCallback(async () => setBank(await api.bankEntries()), [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [libraryRows, bankRows, contactRow] = await Promise.all([
          api.resumeLibrary(),
          api.bankEntries(),
          api.resumeContact(),
        ])
        if (cancelled) return
        setLibrary(libraryRows)
        setBank(bankRows)
        setContact(contactRow)
        // `?draft=` is what the old links said. Honoured so a bookmark from
        // before the two halves became one still lands somewhere sensible.
        const asked = Number(params.get('instance')) || null
        const viaDraft = Number(params.get('draft')) || null
        const openable = libraryRows.filter((row) => row.pushed)
        const wanted =
          openable.find((row) => row.instance_id === asked)?.instance_id ??
          openable.find((row) => row.draft_id === viaDraft)?.instance_id ??
          openable[0]?.instance_id ??
          null
        setInstanceId(wanted)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [params])

  /** Everything this page shows, read off the one document it is editing. */
  const loadDocument = useCallback(async (id) => {
    // The resume first, on its own. Markers that do not pair up make the
    // slot call fail, and a page that had not loaded the resume by then
    // would tell the user there is no resume open rather than show them
    // what is wrong with the one they have.
    const detail = await api.resumeInstance(id)
    setInstance(detail)
    const rows = await api.resumeSlots(id)
    setDocSlots(rows)
    setSlotError(null)
    const [report, proposals] = await Promise.all([
      api.resumeCoverage(id),
      api.resumeProposals(id),
    ])
    setJobPost(detail.job_post_id ? await api.jobPost(detail.job_post_id) : null)
    setCoverage(report.keywords || [])
    setStanding(proposals.find((row) => row.status === 'pending') ?? null)
  }, [])

  useEffect(() => {
    if (!instanceId) {
      setInstance(null)
      setDocSlots(null)
      setJobPost(null)
      setCoverage([])
      setStanding(null)
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        if (!cancelled) await loadDocument(instanceId)
      } catch (err) {
        if (cancelled) return
        // A 409 is markers that do not pair up: a state the composer cannot
        // act on, which the user has to see rather than a document that
        // silently looks like it has none.
        setDocSlots([])
        setSlotError(err.status === 409 ? err.message : null)
        if (err.status !== 409) setError(err.message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [instanceId, loadDocument])

  /** Every write goes through here, so one failure reads the same as any other. */
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

  const refreshSlots = (rows) => {
    setDocSlots(rows)
    setSlotError(null)
  }

  const placeInSlot = (key, position) =>
    act(async () => {
      if (!draggingEntry) return
      refreshSlots(
        await api.placeInResumeSlot(instanceId, key, {
          entry_id: draggingEntry.id,
          position,
        }),
      )
      setCoverage((await api.resumeCoverage(instanceId)).keywords || [])
    })

  const setSlotBlocks = (key, blocks) =>
    act(async () => {
      refreshSlots(await api.writeResumeSlot(instanceId, key, blocks))
      setCoverage((await api.resumeCoverage(instanceId)).keywords || [])
    })

  const rename = (name) => {
    if (!instance || !name || name === instance.name) return
    act(async () => {
      setInstance(await api.updateResumeInstance(instance.id, { name }))
      setLibrary(await api.resumeLibrary())
    })
  }

  const saveContact = (body) =>
    act(async () => {
      setContact(await api.saveResumeContact(body))
      setEditingContact(false)
      // The heading is part of the document, so changing it changes what the
      // page renders. Re-reading is what puts the new one on screen.
      if (instanceId) await loadDocument(instanceId)
    })

  /**
   * The switcher offers every resume, not only the composable ones.
   *
   * A source-only resume has no canvas, so picking it leaves for the surface
   * that can open it. Hiding those would make this list quietly different
   * from the one on the other surface.
   */
  // Every resume, including ones made before documents were the truth.
  // Filtering those out left them unreachable from here, which is to say
  // lost: this is the only page that could ever open them.
  const switcherOptions = library.map((row) => ({
    value: row.pushed ? `instance:${row.instance_id}` : `draft:${row.draft_id}`,
    label: row.pushed ? row.name : `${row.name} (not yet converted)`,
  }))

  /**
   * Open a resume, converting an old draft the moment it is asked for.
   *
   * Conversion on demand rather than all at once on startup: the user is
   * here, looking at it, so a conversion that comes out wrong is something
   * they see immediately rather than discover later.
   */
  const openRow = (value) => {
    const [kind, id] = String(value).split(':')
    if (kind === 'instance') {
      setInstanceId(Number(id) || null)
      return
    }
    act(async () => {
      const adopted = await api.adoptDraft(Number(id))
      setLibrary(await api.resumeLibrary())
      setInstanceId(adopted.id)
    })
  }

  /** A blank resume: an empty slotted skeleton, composable from the start. */
  const createResume = () =>
    act(async () => {
      const created = await api.createResumeInstance({ name: 'New resume', blank: true })
      setLibrary(await api.resumeLibrary())
      setInstanceId(created.id)
    })

  const saveJobPost = (body) =>
    act(async () => {
      const post = await api.createJobPost(body)
      setEditingAd(false)
      setJobPost(post)
      // The ad hangs off whichever half is the resume. A slotted document
      // is tailored and measured through its own source, so attaching it to
      await api.updateResumeInstance(instanceId, { job_post_id: post.id })
      await loadDocument(instanceId)
    })

  const extractKeywords = async () => {
    setExtracting(true)
    try {
      setJobPost(await api.extractJobKeywords(jobPost.id))
      setCoverage((await api.resumeCoverage(instanceId)).keywords || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setExtracting(false)
    }
  }

  // Blocking, like every other Claude call in this app: the request holds
  // open for as long as the model takes, and there is nothing to poll.
  const tailor = async () => {
    setGenerating(true)
    try {
      setProposal(await api.tailorResume(instanceId))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  const resolveProposal = (operations) =>
    act(async () => {
      await api.resolveResumeProposal(
        proposal.id,
        operations ? { action: 'apply', operations } : { action: 'dismiss' },
      )
      setProposal(null)
      await loadDocument(instanceId)
    })

  const runImport = async () => {
    setImporting(true)
    try {
      setImportPreview(await api.importBank())
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setImporting(false)
    }
  }

  const confirmImport = (entries) =>
    act(async () => {
      for (const entry of entries) await api.createBankEntry(entry)
      await reloadBank()
      setImportPreview(null)
    })

  const saveEntry = (patch, bullets) =>
    act(async () => {
      const existing = editing?.id ? editing : null
      const saved = existing
        ? await api.updateBankEntry(existing.id, patch)
        : await api.createBankEntry(patch)
      await syncBullets(saved.id, existing?.bullets || [], bullets)
      await reloadBank()
      setEditing(null)
      if (instanceId) await loadDocument(instanceId)
    })

  const deleteEntry = async () => {
    const confirmed = await confirm({
      key: 'delete-bank-entry',
      title: 'Delete this record?',
      body: (
        <>
          <span className="text-on-surface">{editing.title}</span> and its bullets go for good.
          Resumes that already use it keep their copy of the text.
        </>
      ),
      confirmLabel: 'Delete record',
    })
    if (!confirmed) return
    act(async () => {
      await api.deleteBankEntry(editing.id)
      await reloadBank()
      setEditing(null)
    })
  }

  /**
   * Compile what is already saved, and show the page.
   *
   * There is nothing to push any more. Editing the canvas writes the
   * document, so rendering is only ever a compile of what is already there.
   */
  const render = async () => {
    setRendering(true)
    try {
      const compiled = await api.compileResumeInstance(instanceId)
      setRendered(
        compiled.has_pdf
          ? { url: api.resumePdfUrl(compiled.id, { version: compiled.compiled_at || '' }) }
          : { error: compiled.compile_errors?.[0]?.message || 'That did not compile.' },
      )
      setError(null)
    } catch (err) {
      setRendered({ error: err.message })
    } finally {
      setRendering(false)
    }
  }

  const terms = coverage.map((item) => item.term)

  const actions = (
    <>
      <SurfaceToggle
        active="compose"
        draftId={instance?.draft_id}
        instanceId={instance?.id}
      />
      {/* One position, two modes. Showing the name in a field beside a
          switcher that also showed it read as two inputs for the same thing. */}
      {renaming && instance ? (
        <input
          autoFocus
          className="field w-56"
          defaultValue={instance.name}
          aria-label="Resume name"
          onBlur={(event) => {
            if (!cancelRename.current) rename(event.target.value.trim())
            cancelRename.current = false
            setRenaming(false)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') event.target.blur()
            if (event.key === 'Escape') {
              cancelRename.current = true
              event.target.blur()
            }
          }}
        />
      ) : (
        <Dropdown
          value={instance ? `instance:${instance.id}` : ''}
          onChange={openRow}
          options={switcherOptions}
          ariaLabel="Switch resume"
          className="w-56"
        />
      )}
      {instance && !renaming ? (
        <button
          type="button"
          className="btn"
          aria-label="Rename this resume"
          title="Rename this resume"
          onClick={() => setRenaming(true)}
        >
          <EditIcon />
        </button>
      ) : null}
      <button type="button" className="btn" onClick={createResume} disabled={busy} title="Start another resume">
        <PlusIcon />
        New
      </button>
      {standing ? (
        <button
          type="button"
          className="btn"
          onClick={() => setProposal(standing)}
          title={standing.summary || 'Changes waiting on your decision'}
        >
          Review {standing.operations.length} change
          {standing.operations.length === 1 ? '' : 's'}
        </button>
      ) : null}

    </>
  )

  if (loading) {
    return (
      <PageLayout title="Resumes" icon="resumes" description="Compose a resume for one job ad.">
        <p className="py-6 font-mono text-data text-on-surface-variant">Loading…</p>
      </PageLayout>
    )
  }

  return (
    <PageLayout
      // Titled for the thing, not the surface. One sidebar entry leading to
      // two differently named pages is what made them read as two places.
      title="Resumes"
      icon="resumes"
      description="Compose this resume out of your experience bank, and watch the ad's keywords go covered."
      error={error}
      scroll={false}
      padded={false}
      actions={actions}
    >
      <div className="flex h-full min-h-0">
        <div className="h-full min-h-0 shrink-0 bg-surface-container" style={{ width: bankWidth }}>
          <BankRail
            entries={bank}
            loading={loading}
            importing={importing}
            draggingId={draggingEntry?.id ?? null}
            onImport={runImport}
            onCreate={(kind) => setEditing(kind ? { kind } : {})}
            onEdit={setEditing}
            onDragStart={setDraggingEntry}
            onDragEnd={() => setDraggingEntry(null)}
          />
        </div>

        <ResizeHandle
          orientation="vertical"
          label="Resize the experience bank"
          value={bankWidth}
          onChange={setBankWidth}
          onReset={resetBank}
          min={BANK_WIDTH.min}
          max={BANK_WIDTH.max}
        />

        {!instance ? (
          <div className="flex flex-1 items-center justify-center p-10 text-center">
            <div className="max-w-md space-y-3">
              <p className="text-on-surface-variant">
                No resume in progress. Start one, paste the ad you are writing it for, and compose it
                from the records on the left.
              </p>
              <button type="button" className="btn btn-primary" onClick={createResume} disabled={busy}>
                <PlusIcon />
                Start a resume
              </button>
            </div>
          </div>
        ) : (
          // The coverage pane comes with the resume: an ad pasted before there
          // is anything to measure it against has nowhere to attach.
          <>
            <div className="min-w-0 flex-1">
              <SlotCanvas
                slots={docSlots || []}
                terms={terms}
                droppingEntry={draggingEntry}
                error={slotError}
                contact={contact}
                onPlace={placeInSlot}
                onBlocks={setSlotBlocks}
                onEditContact={() => setEditingContact(true)}
              />
            </div>

            <ResizeHandle
              orientation="vertical"
              label="Resize the coverage panel"
              value={coverageWidth}
              onChange={setCoverageWidth}
              onReset={resetCoverage}
              min={COVERAGE_WIDTH.min}
              max={COVERAGE_WIDTH.max}
              invert
            />

            <aside
              className="h-full min-h-0 shrink-0 bg-surface-container"
              style={{ width: coverageWidth }}
            >
              <CoveragePanel
                jobPost={jobPost}
                coverage={coverage}
                loading={coverageLoading}
                busy={busy}
                extracting={extracting}
                generating={generating}
                onAddJobPost={() => setEditingAd(true)}
                onExtract={extractKeywords}
                onLocate={setFocusedPlacement}
                onTailor={tailor}
                preview={
                  instance
                    ? { ...rendered, rendering, onRender: render, instanceId: instance.id }
                    : null
                }
              />
            </aside>
          </>
        )}
      </div>

      <SlidePanel
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        title={editing?.id ? 'Edit a bank record' : 'Add to your bank'}
        subtitle="Written once here, reusable on every resume."
      >
        {editing ? (
          <BankEntryForm
            // A blank form opened from a group heading is seeded with that
            // group's kind, so the key has to change with it or the open form
            // keeps the kind it was first opened on.
            key={editing.id ?? `new:${editing.kind ?? ''}`}
            entry={editing.id || editing.kind ? editing : null}
            busy={busy}
            onSave={saveEntry}
            onDelete={deleteEntry}
            onCancel={() => setEditing(null)}
          />
        ) : null}
      </SlidePanel>

      <SlidePanel
        open={editingAd}
        onClose={() => setEditingAd(false)}
        title="The job ad"
        subtitle="Its wording is what the coverage panel measures against."
      >
        {editingAd ? <JobAdForm onSave={saveJobPost} busy={busy} /> : null}
      </SlidePanel>

      <SlidePanel
        open={editingContact}
        onClose={() => setEditingContact(false)}
        title="Your contact details"
        subtitle="Printed at the top of every resume you build."
      >
        {editingContact ? (
          <ContactForm
            contact={contact}
            busy={busy}
            onSave={saveContact}
            onCancel={() => setEditingContact(false)}
          />
        ) : null}
      </SlidePanel>

      <SlidePanel
        open={Boolean(importPreview)}
        onClose={() => setImportPreview(null)}
        title="What Claude found in your resume"
      >
        <ImportPreview
          preview={importPreview}
          busy={busy}
          onConfirm={confirmImport}
          onCancel={() => setImportPreview(null)}
        />
      </SlidePanel>

      <SlidePanel
        open={Boolean(proposal)}
        onClose={() => setProposal(null)}
        title="Proposed changes"
        subtitle="Nothing is applied until you apply it."
      >
        {proposal ? (
          <ProposalReview
            proposal={proposal}
            bank={bank}
            busy={busy}
            slots={docSlots}
            onApply={resolveProposal}
            onDismiss={() => resolveProposal(null)}
          />
        ) : null}
      </SlidePanel>
    </PageLayout>
  )
}
