import { useCallback, useEffect, useState } from 'react'
import FilterBar from '../components/FilterBar'
import OpportunityCard from '../components/OpportunityCard'
import OpportunityEditForm from '../components/OpportunityEditForm'
import PageLayout from '../components/PageLayout'
import ResumeFitPanel from '../components/ResumeFitPanel'
import SlidePanel from '../components/SlidePanel'
import SortableTh from '../components/SortableTh'
import StatusBadge, { StatusDot } from '../components/StatusBadge'
import { EditIcon, FitDiamond, TrashIcon } from '../components/icons'
import { useConfirm } from '../components/ConfirmDialog'
import { api } from '../api'
import { deadlineTone, formatDate, formatScore, scoreTone } from '../format'

const COLUMNS = [
  { column: 'relevance_score', label: 'Score' },
  { column: 'title', label: 'Title' },
  { column: 'organization', label: 'Organization' },
  { column: 'type', label: 'Type' },
  { column: 'location', label: 'Location' },
  { column: 'deadline', label: 'Deadline' },
  { column: 'date_found', label: 'Found' },
  { column: 'advice_generated_at', label: 'Fit' },
  { column: 'application_status', label: 'Status' },
  { column: null, label: '' },
]

export default function Opportunities({ onMutate }) {
  const [filters, setFilters] = useState({ sort: 'relevance_score', order: 'desc' })
  const [rows, setRows] = useState([])
  const [sources, setSources] = useState([])
  const [selected, setSelected] = useState(null)
  const [tab, setTab] = useState('details')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [editError, setEditError] = useState(null)
  const [error, setError] = useState(null)
  const confirm = useConfirm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await api.opportunities(filters))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    // Debounce so typing in the search box does not fire a request per keystroke.
    const timer = setTimeout(load, 200)
    return () => clearTimeout(timer)
  }, [load])

  useEffect(() => {
    api.sources().then(setSources).catch(() => setSources([]))
  }, [])

  const openDetail = async (id, nextTab = 'details') => {
    setTab(nextTab)
    setEditError(null)
    try {
      setSelected(await api.opportunity(id))
    } catch (err) {
      setError(err.message)
    }
  }

  const saveEdits = async (changes) => {
    if (!selected) return
    setBusy(true)
    setEditError(null)
    try {
      setSelected(await api.updateOpportunity(selected.id, changes))
      setTab('details')
      await load()
      onMutate?.()
    } catch (err) {
      setEditError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const track = async () => {
    if (!selected) return
    setBusy(true)
    try {
      await api.createApplication({ opportunity_id: selected.id })
      await openDetail(selected.id, tab)
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const saveTags = async (tags) => {
    if (!selected) return
    setBusy(true)
    try {
      setSelected(await api.updateOpportunity(selected.id, { tags }))
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (row) => {
    const confirmed = await confirm({
      key: 'delete-opportunity',
      title: 'Delete this listing?',
      body: (
        <>
          <span className="text-on-surface">{row.title}</span>
          {row.application_status
            ? ' — its tracked application and any saved resume advice go with it.'
            : '.'}{' '}
          Future scrapes will not add it back.
        </>
      ),
      confirmLabel: 'Delete listing',
    })
    if (!confirmed) return
    setDeletingId(row.id)
    try {
      await api.deleteOpportunity(row.id)
      if (selected?.id === row.id) setSelected(null)
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <PageLayout
      title="Opportunities"
      description="Every scraped listing, scored against your resume."
      error={error}
      toolbar={
        <FilterBar filters={filters} onChange={setFilters} sources={sources} resultCount={rows.length} />
      }
    >
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left">
            {COLUMNS.map((header, index) => (
              <SortableTh
                key={header.column || index}
                {...header}
                sticky
                sort={filters.sort}
                order={filters.order}
                onSort={(sort, order) => setFilters({ ...filters, sort, order })}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => openDetail(row.id)}
              className={`cursor-pointer border-b border-outline-variant/60 transition-colors hover:bg-surface-container-high ${
                row.strong_match ? 'border-l-2 border-l-primary' : 'border-l-2 border-l-transparent'
              } ${deletingId === row.id ? 'opacity-40' : ''}`}
            >
              <td className={`px-3 py-2 font-mono font-medium ${scoreTone(row.relevance_score)}`}>
                {formatScore(row.relevance_score)}
              </td>
              <td className="max-w-md px-3 py-2">
                <span className="line-clamp-1 text-on-surface">{row.title}</span>
              </td>
              <td className="max-w-[14rem] px-3 py-2">
                <span className="line-clamp-1 text-on-surface-variant">{row.organization}</span>
              </td>
              <td className="px-3 py-2">
                <StatusBadge value={row.type} kind="type" />
              </td>
              <td className="max-w-[12rem] px-3 py-2">
                <span className="line-clamp-1 text-on-surface-variant">
                  {row.remote ? 'Remote' : row.location || '—'}
                </span>
              </td>
              <td className={`max-w-[9rem] px-3 py-2 font-mono text-data ${deadlineTone(row.deadline)}`}>
                {row.deadline ? formatDate(row.deadline) : '—'}
              </td>
              <td className="whitespace-nowrap px-3 py-2 font-mono text-data text-on-surface-variant">
                {formatDate(row.date_found)}
              </td>
              <td className="px-3 py-2 text-center">
                <button
                  type="button"
                  title={row.advice_generated_at ? 'Resume advice saved — open it' : 'Open the resume fit panel for this listing'}
                  onClick={(event) => {
                    event.stopPropagation()
                    openDetail(row.id, 'fit')
                  }}
                  className={`inline-flex transition-colors hover:text-primary ${
                    row.advice_generated_at ? 'text-primary' : 'text-on-surface-variant'
                  }`}
                >
                  <FitDiamond filled={Boolean(row.advice_generated_at)} />
                </button>
              </td>
              <td className="px-3 py-2 text-center">
                <StatusDot status={row.application_status} />
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  type="button"
                  aria-label={`Delete ${row.title}`}
                  title="Delete this listing"
                  disabled={deletingId === row.id}
                  onClick={(event) => {
                    event.stopPropagation()
                    remove(row)
                  }}
                  className="text-on-surface-variant transition-colors hover:text-error disabled:opacity-40"
                >
                  <TrashIcon />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!loading && !error && rows.length === 0 ? (
        <div className="border-b border-outline-variant px-3 py-10 text-center text-on-surface-variant">
          No opportunities match these filters. Run the scraper from Settings to collect more.
        </div>
      ) : null}
      {loading ? <div className="px-3 py-6 font-mono text-data text-on-surface-variant">Loading…</div> : null}
      <div className="h-8" />

      <SlidePanel
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.title || ''}
        subtitle={selected ? `${selected.organization}${selected.source_name ? ` · ${selected.source_name}` : ''}` : ''}
        footer={
          selected ? (
            <button
              type="button"
              className="btn hover:border-error hover:text-error"
              onClick={() => remove(selected)}
              disabled={deletingId === selected.id}
            >
              <TrashIcon />
              Delete
            </button>
          ) : null
        }
      >
        {selected ? (
          <div className="space-y-5">
            <div className="flex gap-1 border-b border-outline-variant">
              {[
                ['details', 'Details'],
                ['fit', 'Resume fit'],
                ['edit', 'Edit'],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setTab(key)}
                  className={`border-b-2 px-3 py-2 transition-colors ${
                    tab === key
                      ? 'border-primary text-primary'
                      : 'border-transparent text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {key === 'edit' ? <EditIcon className="mr-1.5 inline-block h-3.5 w-3.5" /> : null}
                  {label}
                  {key === 'fit' && selected.advice_generated_at ? (
                    <FitDiamond filled className="ml-2 inline-block h-3.5 w-3.5 text-primary" />
                  ) : null}
                </button>
              ))}
            </div>

            {tab === 'details' ? (
              <OpportunityCard
                opportunity={selected}
                application={selected.application}
                onTrack={track}
                onSaveTags={saveTags}
                busy={busy}
              />
            ) : tab === 'fit' ? (
              <ResumeFitPanel opportunityId={selected.id} />
            ) : (
              <OpportunityEditForm
                key={selected.id}
                opportunity={selected}
                onSave={saveEdits}
                onCancel={() => {
                  setEditError(null)
                  setTab('details')
                }}
                busy={busy}
                error={editError}
              />
            )}
          </div>
        ) : null}
      </SlidePanel>
    </PageLayout>
  )
}
