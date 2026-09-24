import { useCallback, useEffect, useState } from 'react'
import Favicon from '../components/Favicon'
import FilterBar from '../components/FilterBar'
import OpportunityCard from '../components/OpportunityCard'
import OpportunityEditForm from '../components/OpportunityEditForm'
import PageLayout from '../components/PageLayout'
import Pager, { DEFAULT_PAGE_SIZE } from '../components/Pager'
import ResumeFitPanel from '../components/ResumeFitPanel'
import ResumeLinkPicker from '../components/ResumeLinkPicker'
import SlidePanel from '../components/SlidePanel'
import SortableTh from '../components/SortableTh'
import StatusBadge, { StatusDot } from '../components/StatusBadge'
import { EditIcon, FitDiamond, TrashIcon } from '../components/icons'
import { useConfirm } from '../components/ConfirmDialog'
import { api } from '../api'
import { deadlineTone, formatDate, formatScore, scoreTone } from '../format'

/**
 * Every cell of a row, so the row reads as one card.
 *
 * The border is on the cells rather than the `<tr>`, which cannot carry one in
 * a `border-separate` table, and it is always present — transparent when the
 * listing is not a strong match — so highlighting a row does not nudge the
 * others by a pixel.
 */
const cell = (strong, extra = '') =>
  `bg-surface-container py-2.5 border-y transition-colors group-hover:bg-surface-container-high ${
    strong ? 'border-primary/40' : 'border-transparent'
  } ${extra}`

const COLUMNS = [
  { column: null, label: '' },
  { column: 'relevance_score', label: 'Score' },
  { column: 'title', label: 'Title' },
  { column: 'organization', label: 'Organization' },
  { column: 'type', label: 'Type' },
  { column: 'location', label: 'Location' },
  { column: 'deadline', label: 'Deadline' },
  { column: 'date_found', label: 'Found' },
  { column: 'advice_generated_at', label: 'Fit', align: 'center' },
  { column: 'resume', label: 'Resume' },
  { column: 'application_status', label: 'Tracked', align: 'center' },
  { column: null, label: '', align: 'center' },
]

export default function Opportunities({ onMutate }) {
  const [filters, setFilters] = useState({ sort: 'relevance_score', order: 'desc' })
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [total, setTotal] = useState(0)
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
      const { items, total: count } = await api.opportunities({
        ...filters,
        limit: pageSize,
        offset: page * pageSize,
      })
      setRows(items)
      setTotal(count)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [filters, page, pageSize])

  useEffect(() => {
    // Debounce so typing in the search box does not fire a request per keystroke.
    const timer = setTimeout(load, 200)
    return () => clearTimeout(timer)
  }, [load])

  useEffect(() => {
    // Every source, not a page of them: this feeds the filter dropdown.
    api.sources({ limit: 1000 })
      .then(({ items }) => setSources(items))
      .catch(() => setSources([]))
  }, [])

  const changeFilters = (next) => {
    setPage(0)
    setFilters(next)
  }

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

  const linkResume = async (resumeInstanceId) => {
    if (!selected) return
    setBusy(true)
    try {
      setSelected(await api.updateOpportunity(selected.id, { resume_instance_id: resumeInstanceId }))
      await load()
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
      icon="opportunities"
      description="Every scraped listing, scored against your resume."
      error={error}
      toolbar={
        <FilterBar filters={filters} onChange={changeFilters} sources={sources} resultCount={total} />
      }
    >
      {/* `border-separate` rather than `border-collapse`: collapsed borders
          cannot round a row's corners or leave a gap between rows, and a
          table is still the right element — these are columns of comparable
          values, and the headers sort them. */}
      <table className="w-full border-separate border-spacing-y-1.5">
        <thead>
          <tr className="text-left">
            {COLUMNS.map((header, index) => (
              <SortableTh
                key={header.column || index}
                {...header}
                sticky
                sort={filters.sort}
                order={filters.order}
                onSort={(sort, order) => changeFilters({ ...filters, sort, order })}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => openDetail(row.id)}
              className={`group cursor-pointer ${deletingId === row.id ? 'opacity-40' : ''}`}
            >
              {/* The rounding lives on the end cells; a <tr> cannot carry a
                  border-radius that its cells will respect. */}
              {/* Asymmetric on purpose. The gap the eye reads on the right
                  is this cell's padding plus the next cell's, so matching
                  them numerically would leave the icon crowded against the
                  card's border. 16px left, 4px + the neighbour's 12px right. */}
              <td className={cell(row.strong_match, 'w-10 rounded-l-lg border-l pl-4 pr-1')}>
                <span className="flex items-center justify-center">
                  <Favicon url={row.url} />
                </span>
              </td>
              <td className={cell(row.strong_match, `px-3 font-mono font-medium ${scoreTone(row.relevance_score)}`)}>
                {formatScore(row.relevance_score)}
              </td>
              <td className={cell(row.strong_match, 'max-w-md px-3')}>
                <span className="line-clamp-1 text-on-surface">{row.title}</span>
              </td>
              <td className={cell(row.strong_match, 'max-w-[14rem] px-3')}>
                <span className="line-clamp-1 text-on-surface-variant">{row.organization}</span>
              </td>
              <td className={cell(row.strong_match, 'px-3')}>
                <StatusBadge value={row.type} kind="type" />
              </td>
              <td className={cell(row.strong_match, 'max-w-[12rem] px-3')}>
                <span className="line-clamp-1 text-on-surface-variant">
                  {row.remote ? 'Remote' : row.location || '—'}
                </span>
              </td>
              <td className={cell(row.strong_match, `max-w-[9rem] px-3 font-mono text-data ${deadlineTone(row.deadline)}`)}>
                {row.deadline ? formatDate(row.deadline) : '—'}
              </td>
              <td className={cell(row.strong_match, 'whitespace-nowrap px-3 font-mono text-data text-on-surface-variant')}>
                {formatDate(row.date_found)}
              </td>
              {/* Flex-centred rather than left to inline layout. An inline
                  icon sits on the text baseline, not the cell's middle, and
                  since each glyph has a different box the icons end up on
                  three different heights across one row. */}
              <td className={cell(row.strong_match, 'px-3')}>
                <span className="flex items-center justify-center">
                  <button
                    type="button"
                    title={row.advice_generated_at ? 'Resume advice saved — open it' : 'Open the resume fit panel for this listing'}
                    onClick={(event) => {
                      event.stopPropagation()
                      openDetail(row.id, 'fit')
                    }}
                    className={`flex items-center transition-colors hover:text-primary ${
                      row.advice_generated_at ? 'text-primary' : 'text-on-surface-variant'
                    }`}
                  >
                    <FitDiamond filled={Boolean(row.advice_generated_at)} />
                  </button>
                </span>
              </td>
              <td className={cell(row.strong_match, 'max-w-[9rem] px-3')}>
                <span className="line-clamp-1 font-mono text-data text-on-surface-variant">
                  {row.resume_instance_name || '—'}
                </span>
              </td>
              <td className={cell(row.strong_match, 'px-3')}>
                <span className="flex items-center justify-center">
                  <StatusDot status={row.application_status} />
                </span>
              </td>
              <td className={cell(row.strong_match, 'rounded-r-lg border-r px-3')}>
                <span className="flex items-center justify-center">
                  <button
                    type="button"
                    aria-label={`Delete ${row.title}`}
                    title="Delete this listing"
                    disabled={deletingId === row.id}
                    onClick={(event) => {
                      event.stopPropagation()
                      remove(row)
                    }}
                    className="flex items-center text-on-surface-variant transition-colors hover:text-error disabled:opacity-40"
                  >
                    <TrashIcon />
                  </button>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {!loading && !error && rows.length === 0 ? (
        <div className="rounded-lg bg-surface-container px-3 py-10 text-center text-on-surface-variant">
          No opportunities match these filters. Run the scraper from Settings to collect more.
        </div>
      ) : null}
      {loading ? <div className="px-3 py-6 font-mono text-data text-on-surface-variant">Loading…</div> : null}

      <Pager
        page={page}
        pageSize={pageSize}
        total={total}
        label="listings"
        onPage={setPage}
        onPageSize={(size) => {
          // Keep the first row of the current page in view rather than
          // jumping back to the top of the table.
          setPage(Math.floor((page * pageSize) / size))
          setPageSize(size)
        }}
      />
      <div className="h-4" />

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

            {/* Under the tabs rather than inside one: which resume was tailored
                for this listing belongs to the listing, not to a single view. */}
            <ResumeLinkPicker opportunity={selected} onChange={linkResume} busy={busy} />

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
