import { useCallback, useEffect, useState } from 'react'
import BankEntryForm from '../components/BankEntryForm'
import BankRail from '../components/BankRail'
import CoveragePanel from '../components/CoveragePanel'
import DraftCanvas from '../components/DraftCanvas'
import Dropdown from '../components/Dropdown'
import PageLayout from '../components/PageLayout'
import ProposalReview from '../components/ProposalReview'
import SlidePanel from '../components/SlidePanel'
import { ResizeHandle, usePanelSize } from '../components/Resizable'
import { useConfirm } from '../components/ConfirmDialog'
import { PlusIcon } from '../components/icons'
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
                      <li key={position}>{bullet.text}</li>
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
  const [importPreview, setImportPreview] = useState(null)
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
        const [draftRows, bankRows] = await Promise.all([api.drafts(), api.bankEntries()])
        if (cancelled) return
        setDrafts(draftRows)
        setBank(bankRows)
        setDraftId(draftRows[0]?.id ?? null)
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

  useEffect(() => {
    if (!draftId) {
      setDraft(null)
      setJobPost(null)
      setCoverage([])
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
        await refreshCoverage(detail.id, Boolean(detail.job_post_id))
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [draftId, refreshCoverage])

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

  const createDraft = () =>
    act(async () => {
      const created = await api.createDraft({ name: 'New resume' })
      setDrafts(await api.drafts())
      setDraftId(created.id)
    })

  const saveJobPost = (body) =>
    act(async () => {
      const post = await api.createJobPost(body)
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
      await refreshCoverage(draft.id, Boolean(draft.job_post_id))
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
      for (const entry of entries) {
        const { bullets, ...fields } = entry
        const created = await api.createBankEntry(fields)
        for (const bullet of bullets || []) {
          await api.createBankBullet(created.id, { text: bullet.text })
        }
      }
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

  const push = () =>
    act(async () => {
      try {
        remember(await api.pushDraft(draft.id))
        return
      } catch (err) {
        // A refused push is a 409 carrying both texts, not a 200 saying no.
        if (err.status !== 409) throw err
      }
      // The LaTeX editor is still the escape hatch, so a hand-edit there must
      // not be overwritten without being shown first.
      const confirmed = await confirm({
        title: 'That resume was edited by hand',
        body: 'The LaTeX has changed since this draft last wrote it. Pushing again replaces the whole document with what is on the canvas.',
        confirmLabel: 'Replace it',
      })
      if (confirmed) remember(await api.pushDraft(draft.id, true))
    })

  const terms = coverage.map((item) => item.term)

  const actions = (
    <>
      <Dropdown
        value={draftId ?? ''}
        onChange={(value) => setDraftId(value ? Number(value) : null)}
        options={drafts.map((row) => ({ value: row.id, label: row.name }))}
        ariaLabel="Resume draft"
        className="w-56"
      />
      <button type="button" className="btn" onClick={createDraft} disabled={busy} title="Start another resume">
        <PlusIcon />
        New
      </button>
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
      <PageLayout title="Builder" icon="builder" description="Compose a resume for one job ad.">
        <p className="py-6 font-mono text-data text-on-surface-variant">Loading…</p>
      </PageLayout>
    )
  }

  return (
    <PageLayout
      title="Builder"
      icon="builder"
      description="Compose a resume for one job ad out of your experience bank, and watch its keywords go covered."
      error={error}
      scroll={false}
      contentClassName="px-0 pb-0"
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
            onCreate={() => setEditing({})}
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
              <DraftCanvas
                body={draft.body}
                bank={bank}
                terms={terms}
                droppingEntry={draggingEntry}
                focusedPlacement={focusedPlacement}
                onChange={commit}
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
                onSaveJobPost={saveJobPost}
                onExtract={extractKeywords}
                onLocate={setFocusedPlacement}
                onTailor={tailor}
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
            key={editing.id ?? 'new'}
            entry={editing.id ? editing : null}
            busy={busy}
            onSave={saveEntry}
            onDelete={deleteEntry}
            onCancel={() => setEditing(null)}
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
