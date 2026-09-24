import { useCallback, useEffect, useState } from 'react'
import Favicon from '../components/Favicon'
import PageLayout from '../components/PageLayout'
import Pager, { DEFAULT_PAGE_SIZE } from '../components/Pager'
import SlidePanel from '../components/SlidePanel'
import SourceForm from '../components/SourceForm'
import SourceDiscoveryPanel from '../components/SourceDiscoveryPanel'
import StatusBadge from '../components/StatusBadge'
import SortableTh from '../components/SortableTh'
import Tooltip from '../components/Tooltip'
import { AI_CALL_TITLE, AiSpark, BlockedIcon, EditIcon, PlusIcon, TrashIcon, WarnIcon } from '../components/icons'
import { useConfirm } from '../components/ConfirmDialog'
import {
  ChipGroup,
  ClearFilters,
  ResultCount,
  SearchInput,
  SelectFilter,
  ToggleChip,
  hasActiveFilters,
} from '../components/filters'
import { SOURCE_TYPES, api } from '../api'
import { formatDate, formatDateTime, relativeTime } from '../format'

/**
 * How the last scrape attempt ended, shown in place of the timestamp.
 *
 * Without this the column lies by omission: `last_scraped` is written on every
 * attempt, successful or not, so a source that has failed every run for a week
 * still reads "5 minutes ago".
 *
 * Two failures, deliberately not the same colour. **Blocked** is red and final —
 * the host is refusing us and retrying by hand will not help. **Failed** is the
 * softer tertiary tone, because a timeout or a 500 is usually worth another go.
 */
const SCRAPE_STATES = {
  blocked: {
    label: 'Blocked',
    Icon: BlockedIcon,
    tone: 'border-error/60 bg-error/10 text-error',
    fallback: 'Refused by the host',
  },
  error: {
    label: 'Failed',
    Icon: WarnIcon,
    tone: 'border-tertiary/60 bg-tertiary/10 text-tertiary',
    fallback: 'The last scrape did not finish',
  },
}

function LastScraped({ source }) {
  const state = SCRAPE_STATES[source.last_status]
  if (!state) {
    return <span className="font-mono text-data text-on-surface-variant">{relativeTime(source.last_scraped)}</span>
  }
  const { label, Icon, tone, fallback } = state
  return (
    <Tooltip
      label={`${source.last_error || fallback} · last tried ${relativeTime(source.last_scraped)}`}
      placement="top"
    >
      <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-[2px] font-mono text-data ${tone}`}>
        <Icon className="h-3 w-3" />
        {label}
      </span>
    </Tooltip>
  )
}

// Shared by every cell so the row reads as one card rather than a table row.
// The transparent border keeps these rows the same height and shape as the
// listings table, where the border turns blue on a strong match.
const CELL =
  'bg-surface-container py-2.5 border-y border-transparent transition-colors group-hover:bg-surface-container-high'

const COLUMNS = [
  { column: null, label: '' },
  { column: 'name', label: 'Name' },
  { column: 'type', label: 'Type' },
  { column: 'active', label: 'Active' },
  { column: 'last_scraped', label: 'Last scraped' },
  { column: 'last_result_count', label: 'Results' },
  { column: 'date_added', label: 'Added' },
  { column: 'added_by', label: 'By' },
  { column: null, label: '' },
]

function SourceFilterBar({ filters, onChange, resultCount }) {
  const set = (patch) => onChange({ ...filters, ...patch })
  return (
    <div className="space-y-3 pb-4">
      <ChipGroup
        label="Type"
        options={SOURCE_TYPES}
        selected={filters.type || []}
        onChange={(type) => set({ type })}
      />
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          value={filters.search}
          onChange={(search) => set({ search })}
          placeholder="Search name, URL, notes…"
        />
        <SelectFilter
          value={filters.active}
          onChange={(active) => set({ active })}
          options={[
            { value: 'true', label: 'Active only' },
            { value: 'false', label: 'Paused only' },
          ]}
          placeholder="Active and paused"
        />
        <SelectFilter
          value={filters.added_by}
          onChange={(added_by) => set({ added_by })}
          options={[
            { value: 'user', label: 'Added by me' },
            { value: 'claude', label: 'Added by Claude' },
          ]}
          placeholder="Any origin"
        />
        <SelectFilter
          value={filters.scrape_method}
          onChange={(scrape_method) => set({ scrape_method: scrape_method ? [scrape_method] : undefined })}
          options={['html', 'api', 'search_query']}
          placeholder="Any method"
        />
        <ToggleChip
          active={filters.never_scraped === 'true'}
          onClick={() => set({ never_scraped: filters.never_scraped === 'true' ? undefined : 'true' })}
          title="Sources that have never been scraped"
        >
          Never scraped
        </ToggleChip>
        <ClearFilters
          show={hasActiveFilters(filters)}
          onClear={() => onChange({ sort: filters.sort, order: filters.order })}
        />
        <ResultCount count={resultCount} noun="source" />
      </div>
    </div>
  )
}

export default function Sources({ onMutate }) {
  const [filters, setFilters] = useState({ sort: 'name', order: 'asc' })
  const [sources, setSources] = useState([])
  const [proposals, setProposals] = useState([])
  const [status, setStatus] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [formError, setFormError] = useState(null)
  const [showDiscovery, setShowDiscovery] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const [discoveryError, setDiscoveryError] = useState(null)
  // Namespaced, not a bare id: sources and proposals are separate id sequences,
  // so a plain number left "Scrape" on source 3 and "Approve" on proposal 3
  // disabling each other.
  const [busyId, setBusyId] = useState(null)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const confirm = useConfirm()

  const load = useCallback(async () => {
    try {
      const [nextSources, nextProposals, nextStatus] = await Promise.all([
        api.sources({ ...filters, limit: pageSize, offset: page * pageSize }),
        api.proposals(),
        api.scrapeStatus(),
      ])
      setSources(nextSources.items)
      setTotal(nextSources.total)
      setProposals(nextProposals)
      setStatus(nextStatus)
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [filters, page, pageSize])

  // A narrowed filter can leave you on a page that no longer exists.
  const changeFilters = (next) => {
    setPage(0)
    setFilters(next)
  }

  useEffect(() => {
    const timer = setTimeout(load, 200)
    return () => clearTimeout(timer)
  }, [load])

  const toggleActive = async (source) => {
    try {
      await api.updateSource(source.id, { active: !source.active })
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
    }
  }

  const createSource = async (body) => {
    setBusyId('new')
    setFormError(null)
    try {
      await api.createSource(body)
      setShowForm(false)
      await load()
      onMutate?.()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  const saveSource = async (changes) => {
    if (!editing) return
    setBusyId(`save:${editing.id}`)
    setFormError(null)
    try {
      await api.updateSource(editing.id, changes)
      setEditing(null)
      await load()
      onMutate?.()
    } catch (err) {
      setFormError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  const remove = async (source) => {
    const confirmed = await confirm({
      key: 'delete-source',
      title: 'Delete this source?',
      body: (
        <>
          <span className="text-on-surface">{source.name}</span> will no longer be scraped. Opportunities
          already found from it are kept.
        </>
      ),
      confirmLabel: 'Delete source',
    })
    if (!confirmed) return
    try {
      await api.deleteSource(source.id)
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
    }
  }

  /*
   * Keep the run status current while a scrape is in flight.
   *
   * Every row's Scrape button is gated on `status.running`, but `load()` only
   * runs on mount and after a mutation — so a scrape started from Settings, or
   * by the scheduler, left every button here clickable for its whole duration.
   * Polling stays slow when nothing is running.
   */
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const next = await api.scrapeStatus()
        if (cancelled) return
        const finished = status?.running && !next.running
        setStatus(next)
        // A run that just ended rewrote every row it touched.
        if (finished) await load()
      } catch {
        /* a transient polling failure is not worth surfacing */
      }
    }
    const timer = setInterval(tick, status?.running ? 2500 : 20_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [status?.running, load])

  const scrapeOne = async (source) => {
    setBusyId(`scrape:${source.id}`)
    try {
      await api.scrapeSource(source.id)
      // Reload, don't just refresh the run status: this scrape is what sets the
      // row's result count and its Blocked/Failed tag, and without this the row
      // keeps showing pre-scrape values until something else reloads the page.
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
      await load()
    } finally {
      setBusyId(null)
    }
  }

  const discover = async (body) => {
    setDiscovering(true)
    setDiscoveryError(null)
    try {
      await api.discoverSources(body)
      await load()
      onMutate?.()
    } catch (err) {
      setDiscoveryError(err.message)
    } finally {
      setDiscovering(false)
    }
  }

  const decide = async (proposal, approve) => {
    setBusyId(`proposal:${proposal.id}`)
    try {
      await (approve ? api.approveProposal(proposal.id) : api.rejectProposal(proposal.id))
      await load()
      onMutate?.()
    } catch (err) {
      setDiscoveryError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <PageLayout
      title="Sources"
      icon="sources"
      description={`${sources.length} shown · every active source is scraped.`}
      error={error}
      actions={
        <>
          <div className="rounded border border-outline-variant bg-surface-container px-3 py-2 font-mono text-data text-on-surface-variant">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${status?.running ? 'bg-tertiary' : 'bg-primary'}`}
                aria-hidden="true"
              />
              {status?.running ? 'Scrape running' : 'Idle'}
            </div>
            <div>last {relativeTime(status?.last_run)}</div>
            <div>next {formatDateTime(status?.next_run)}</div>
          </div>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setFormError(null)
              setShowForm((value) => !value)
            }}
          >
            <PlusIcon />
            Add source
          </button>
          <button
            type="button"
            className="btn btn-primary"
            title={AI_CALL_TITLE}
            onClick={() => setShowDiscovery(true)}
          >
            <AiSpark />
            Discover sources
            {proposals.length ? <span className="font-mono text-data">({proposals.length})</span> : null}
          </button>
        </>
      }
      banner={
        showForm ? (
          <div className="mb-5 rounded border border-outline-variant bg-surface-container p-4 animate-fade-in">
            <SourceForm
              onSubmit={createSource}
              onCancel={() => {
                setFormError(null)
                setShowForm(false)
              }}
              busy={busyId === 'new'}
              error={formError}
            />
          </div>
        ) : null
      }
      toolbar={<SourceFilterBar filters={filters} onChange={changeFilters} resultCount={total} />}
    >
      <div>
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
            {sources.length === 0 && !error ? (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="rounded-lg bg-surface-container px-3 py-10 text-center text-on-surface-variant"
                >
                  No sources match these filters.
                </td>
              </tr>
            ) : null}
            {sources.map((source) => (
              <tr key={source.id} className={`group ${source.active ? '' : 'opacity-50'}`}>
                {/* Asymmetric on purpose. The gap the eye reads on the right
                    is this cell's padding plus the next cell's, so matching
                    them numerically would leave the icon crowded against the
                    card's border. 16px left, 4px + the neighbour's 12px right. */}
                <td className={`${CELL} w-10 rounded-l-lg border-l pl-4 pr-1`}>
                  <span className="flex items-center justify-center">
                    <Favicon url={source.url} />
                  </span>
                </td>
                <td className={`${CELL} max-w-sm px-3`}>
                  <div className="line-clamp-1 text-on-surface">{source.name}</div>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="line-clamp-1 font-mono text-data text-on-surface-variant hover:text-primary"
                  >
                    {source.url}
                  </a>
                </td>
                <td className={`${CELL} px-3`}>
                  <StatusBadge value={source.type} kind="source" />
                </td>
                <td className={`${CELL} px-3`}>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={source.active}
                    onClick={() => toggleActive(source)}
                    title={source.active ? 'Deactivate' : 'Activate'}
                    className={`relative h-5 w-9 rounded-full border transition-colors ${
                      source.active ? 'border-primary bg-primary/25' : 'border-outline-variant bg-surface'
                    }`}
                  >
                    <span
                      className={`absolute top-[2px] h-3.5 w-3.5 rounded-full transition-all ${
                        source.active ? 'left-[18px] bg-primary' : 'left-[2px] bg-on-surface-variant'
                      }`}
                    />
                  </button>
                </td>
                <td className={`${CELL} px-3`}>
                  <LastScraped source={source} />
                </td>
                <td className={`${CELL} px-3 font-mono text-data text-on-surface`}>
                  {source.last_result_count ?? '—'}
                </td>
                <td className={`${CELL} px-3 font-mono text-data text-on-surface-variant`}>
                  {formatDate(source.date_added)}
                </td>
                <td className={`${CELL} px-3`}>
                  <span
                    className={`font-mono text-data ${source.added_by === 'claude' ? 'text-primary' : 'text-on-surface-variant'}`}
                  >
                    {source.added_by}
                  </span>
                </td>
                <td className={`${CELL} rounded-r-lg border-r px-3`}>
                  <div className="flex justify-end gap-2">
                    {source.last_status === 'blocked' ? (
                      /* No point spending a request the host will refuse. Not
                         a dead end: scheduled runs still try, and the tag
                         clears the moment one gets through — as does editing
                         the URL, which is the usual fix. */
                      <Tooltip
                        label={`${source.last_error || 'Refused by the host'}. Scheduled runs keep trying; editing the URL re-enables this.`}
                        placement="top"
                      >
                        <button type="button" className="btn" aria-disabled="true">
                          <AiSpark />
                          Scrape
                        </button>
                      </Tooltip>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        title={`${AI_CALL_TITLE} — every listing found here is classified by Claude`}
                        disabled={busyId === `scrape:${source.id}` || status?.running}
                        onClick={() => scrapeOne(source)}
                      >
                        <AiSpark />
                        Scrape
                      </button>
                    )}
                    <button
                      type="button"
                      aria-label={`Edit ${source.name}`}
                      title="Edit this source"
                      className="px-2 text-on-surface-variant transition-colors hover:text-primary"
                      onClick={() => {
                        setFormError(null)
                        setEditing(source)
                      }}
                    >
                      <EditIcon />
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${source.name}`}
                      title="Delete this source"
                      className="px-2 text-on-surface-variant transition-colors hover:text-error"
                      onClick={() => remove(source)}
                    >
                      <TrashIcon />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pager
        page={page}
        pageSize={pageSize}
        total={total}
        label="sources"
        onPage={setPage}
        onPageSize={(size) => {
          setPage(Math.floor((page * pageSize) / size))
          setPageSize(size)
        }}
      />
      <div className="h-4" />

      <SlidePanel
        open={Boolean(editing)}
        onClose={() => {
          setFormError(null)
          setEditing(null)
        }}
        title={editing ? `Edit ${editing.name}` : ''}
        subtitle="Opportunities already found from this source are kept."
      >
        {editing ? (
          <SourceForm
            key={editing.id}
            source={editing}
            onSubmit={saveSource}
            onCancel={() => {
              setFormError(null)
              setEditing(null)
            }}
            busy={busyId === `save:${editing.id}`}
            error={formError}
          />
        ) : null}
      </SlidePanel>

      <SlidePanel
        open={showDiscovery}
        onClose={() => setShowDiscovery(false)}
        title="Source discovery"
        subtitle="Claude-proposed boards, programs and career pages"
      >
        <SourceDiscoveryPanel
          proposals={proposals}
          discovering={discovering}
          error={discoveryError}
          busyId={busyId}
          onDiscover={discover}
          onApprove={(proposal) => decide(proposal, true)}
          onReject={(proposal) => decide(proposal, false)}
        />
      </SlidePanel>
    </PageLayout>
  )
}
