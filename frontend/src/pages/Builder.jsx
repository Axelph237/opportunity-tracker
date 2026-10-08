import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import BankEntryForm from '../components/BankEntryForm'
import BankRail from '../components/BankRail'
import ContactForm from '../components/ContactForm'
import CoveragePanel, { JobAdForm } from '../components/CoveragePanel'
import DraftCanvas from '../components/DraftCanvas'
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
  const [drafts, setDrafts] = useState([])
  const [draftId, setDraftId] = useState(null)
  const [draft, setDraft] = useState(null)
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
  // composed by rewriting its source; one without is still a draft.
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

  /**
   * Anything waiting on a decision, drift included.
   *
   * This GET has a side effect: reading the list is what runs the drift
   * check, so a reworded bank record surfaces only once somebody asks.
   */
  const refreshProposals = useCallback(async (id) => {
    const pending = (await api.draftProposals(id)).filter((row) => row.status === 'pending')
    setStanding(pending[0] ?? null)
  }, [])

  const refreshCoverage = useCallback(async (id, hasJobPost) => {
    // Nothing to measure against until an ad is attached, and asking anyway
    // would put a permanent error on a draft that is simply not started yet.
    if (!id || !hasJobPost) {
      setCoverage([])
      return
    }
    setCoverageLoading(true)
    try {
      const report = await api.draftCoverage(id)
      setCoverage(report?.keywords || [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setCoverageLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [draftRows, bankRows, contactRow, libraryRows] = await Promise.all([
          api.drafts(),
          api.bankEntries(),
          api.resumeContact(),
          api.resumeLibrary(),
        ])
        if (cancelled) return
        setDrafts(draftRows)
        setBank(bankRows)
        setContact(contactRow)
        setLibrary(libraryRows)
        // Arriving from a resume picks that resume's draft, not the newest.
        const asked = Number(params.get('draft'))
        const wanted = draftRows.some((row) => row.id === asked) ? asked : null
        setDraftId(wanted ?? draftRows[0]?.id ?? null)
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

  // A draft that has been pushed may already be a slotted document, in which
  // case the canvas works on the source rather than on the draft's body.
  useEffect(() => {
    const instanceId = draft?.resume_instance_id
    if (!instanceId) {
      setDocSlots(null)
      setSlotError(null)
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        const rows = await api.resumeSlots(instanceId)
        if (!cancelled) {
          setDocSlots(rows.length ? rows : null)
          setSlotError(null)
        }
      } catch (err) {
        // A 409 means the markers do not pair up, which is a state the
        // composer cannot act on and the user has to see rather than a
        // document that silently looks like it has no slots.
        if (!cancelled) {
          setDocSlots(err.status === 409 ? [] : null)
          setSlotError(err.status === 409 ? err.message : null)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [draft?.resume_instance_id, draft?.updated_at])

  const refreshSlots = (rows) => {
    setDocSlots(rows.length ? rows : null)
    setSlotError(null)
  }

  const placeInSlot = (key, position) =>
    act(async () => {
      if (!draggingEntry) return
      refreshSlots(
        await api.placeInResumeSlot(draft.resume_instance_id, key, {
          entry_id: draggingEntry.id,
          position,
        }),
      )
    })

  const setSlotBlocks = (key, blocks) =>
    act(async () => {
      refreshSlots(await api.writeResumeSlot(draft.resume_instance_id, key, blocks))
    })

  useEffect(() => {
    if (!draftId) {
      setDraft(null)
      setJobPost(null)
      setCoverage([])
      setStanding(null)
      return undefined
    }
    let cancelled = false
    ;(async () => {
      try {
        const detail = await api.draft(draftId)
        if (cancelled) return
        setDraft(detail)
        setJobPost(detail.job_post_id ? await api.jobPost(detail.job_post_id) : null)
        if (cancelled) return
        setError(null)
        await Promise.all([
          refreshCoverage(detail.id, Boolean(detail.job_post_id)),
          refreshProposals(detail.id),
        ])
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [draftId, refreshCoverage, refreshProposals])

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

  /** The single write path for the document. Optimistic, so a drop feels instant. */
  const commit = useCallback(
    async (body) => {
      if (!draft) return
      setDraft((current) => ({ ...current, body }))
      try {
        const saved = await api.updateDraft(draft.id, { body })
        setDraft((current) => (current?.id === saved.id ? { ...current, ...saved } : current))
        setError(null)
        await refreshCoverage(draft.id, Boolean(draft.job_post_id))
      } catch (err) {
        setError(err.message)
      }
    },
    [draft, refreshCoverage],
  )

  const placeEntry = (entryId, sectionRef) =>
    act(async () => {
      setDraft(await api.placeDraftEntry(draft.id, { entry_id: entryId, section_ref: sectionRef }))
      await refreshCoverage(draft.id, Boolean(draft.job_post_id))
    })

  const renameDraft = (name) => {
    if (!draft || !name || name === draft.name) return
    act(async () => {
      const saved = await api.updateDraft(draft.id, { name })
      setDraft((current) => ({ ...current, ...saved }))
      setDrafts(await api.drafts())
    })
  }

  const saveContact = (body) =>
    act(async () => {
      setContact(await api.saveResumeContact(body))
      setEditingContact(false)
      // The heading is part of what a push writes, so a draft already pushed
      // is now behind. Re-reading the draft is what refreshes that warning.
      if (draftId) setDraft(await api.draft(draftId))
    })

  /**
   * The switcher offers every resume, not only the composable ones.
   *
   * A source-only resume has no canvas, so picking it leaves for the surface
   * that can open it. Hiding those would make this list quietly different
   * from the one on the other surface.
   */
  const switcherOptions = library.map((row) => ({
    value: row.composed ? `draft:${row.draft_id}` : `instance:${row.instance_id}`,
    label: row.name,
  }))

  const openRow = (value) => {
    const [kind, id] = String(value).split(':')
    if (kind === 'draft') setDraftId(Number(id))
    else navigate(`/resumes?instance=${id}`)
  }

  const createDraft = () =>
    act(async () => {
      const created = await api.createDraft({ name: 'New resume' })
      setDrafts(await api.drafts())
      setDraftId(created.id)
    })

  const saveJobPost = (body) =>
    act(async () => {
      const post = await api.createJobPost(body)
      setEditingAd(false)
      setJobPost(post)
      const saved = await api.updateDraft(draft.id, { job_post_id: post.id })
      setDraft((current) => ({ ...current, ...saved }))
    })

  const extractKeywords = async () => {
    setExtracting(true)
    try {
      setJobPost(await api.extractJobKeywords(jobPost.id))
      await refreshCoverage(draft.id, true)
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
      setProposal(await api.tailorDraft(draft.id))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  const resolveProposal = (operations) =>
    act(async () => {
      const updated = await api.resolveProposal(
        proposal.id,
        operations ? { action: 'apply', operations } : { action: 'dismiss' },
      )
      if (updated?.id) setDraft(updated)
      setProposal(null)
      await Promise.all([
        refreshCoverage(draft.id, Boolean(draft.job_post_id)),
        refreshProposals(draft.id),
      ])
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
      // Rewording a record here is what puts a draft out of date with it.
      if (draft) await refreshProposals(draft.id)
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

  const remember = (result) =>
    setDraft((current) => ({
      ...current,
      pushed_at: result?.pushed_at ?? current.pushed_at,
      resume_instance_id: result?.resume_instance_id ?? current.resume_instance_id,
    }))

  /** Push, compile, and show the page, without leaving for the Resumes tab. */
  const pushAndRender = async () => {
    setRendering(true)
    try {
      const result = await api.pushDraft(draft.id)
      remember(result)
      const compiled = await api.compileResumeInstance(result.resume_instance_id)
      setRendered(
        compiled.has_pdf
          ? { url: api.resumePdfUrl(compiled.id, { version: compiled.compiled_at || '' }) }
          : { error: compiled.compile_errors?.[0]?.message || 'That did not compile.' },
      )
      setError(null)
    } catch (err) {
      // A 409 means a hand-edit is in the way, which the Push button already
      // explains and offers to resolve. Saying it twice, differently, would not.
      setRendered({ error: err.status === 409 ? 'Push it first: that resume was edited by hand.' : err.message })
    } finally {
      setRendering(false)
    }
  }

  const push = () =>
    act(async () => {
      let edited = null
      try {
        remember(await api.pushDraft(draft.id))
        return
      } catch (err) {
        if (err.status !== 409) throw err
        edited = err.detail?.current_latex ?? ''
      }
      // The LaTeX editor is still the escape hatch, so a hand-edit there is
      // shown before it is replaced, rather than described and guessed at.
      const confirmed = await confirm({
        title: 'That resume was edited by hand',
        body: (
          <>
            Pushing again replaces the whole document with what is on the canvas. This is what
            is in that resume now:
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded border border-outline-variant bg-surface p-2 font-code text-data">
              {edited}
            </pre>
          </>
        ),
        confirmLabel: 'Replace it',
      })
      if (confirmed) remember(await api.pushDraft(draft.id, true))
    })

  const terms = coverage.map((item) => item.term)

  const actions = (
    <>
      <SurfaceToggle
        active="compose"
        draftId={draft?.id}
        instanceId={draft?.resume_instance_id}
      />
      {/* One position, two modes. Showing the name in a field beside a
          switcher that also showed it read as two inputs for the same thing. */}
      {renaming && draft ? (
        <input
          autoFocus
          className="field w-56"
          defaultValue={draft.name}
          aria-label="Resume name"
          onBlur={(event) => {
            if (!cancelRename.current) renameDraft(event.target.value.trim())
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
          value={draft ? `draft:${draft.id}` : ''}
          onChange={openRow}
          options={switcherOptions}
          ariaLabel="Switch resume"
          className="w-56"
        />
      )}
      {draft && !renaming ? (
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
      <button type="button" className="btn" onClick={createDraft} disabled={busy} title="Start another resume">
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
      {draft ? (
        <button
          type="button"
          className="btn"
          onClick={push}
          disabled={busy}
          title="Write this draft into a resume version you can render"
        >
          Push to resume
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

        {!draft ? (
          <div className="flex flex-1 items-center justify-center p-10 text-center">
            <div className="max-w-md space-y-3">
              <p className="text-on-surface-variant">
                No resume in progress. Start one, paste the ad you are writing it for, and compose it
                from the records on the left.
              </p>
              <button type="button" className="btn btn-primary" onClick={createDraft} disabled={busy}>
                <PlusIcon />
                Start a resume
              </button>
            </div>
          </div>
        ) : (
          // The coverage pane comes with the draft: an ad pasted before there
          // is anything to measure it against has nowhere to attach.
          <>
            <div className="min-w-0 flex-1">
              {docSlots || slotError ? (
                <SlotCanvas
                  slots={docSlots || []}
                  terms={terms}
                  droppingEntry={draggingEntry}
                  error={slotError}
                  onPlace={placeInSlot}
                  onBlocks={setSlotBlocks}
                />
              ) : (
              <DraftCanvas
                body={draft.body}
                bank={bank}
                terms={terms}
                droppingEntry={draggingEntry}
                focusedPlacement={focusedPlacement}
                contact={contact}
                onChange={commit}
                onPlace={placeEntry}
                onEditContact={() => setEditingContact(true)}
              />
              )}
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
                  draft
                    ? {
                        ...rendered,
                        rendering,
                        onRender: pushAndRender,
                        instanceId: draft.resume_instance_id,
                      }
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
            body={draft?.body}
            bank={bank}
            busy={busy}
            onApply={resolveProposal}
            onDismiss={() => resolveProposal(null)}
          />
        ) : null}
      </SlidePanel>
    </PageLayout>
  )
}
