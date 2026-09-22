import { useCallback, useEffect, useState } from 'react'
import Dropdown from '../components/Dropdown'
import PageLayout from '../components/PageLayout'
import { ExternalLinkIcon, StarIcon } from '../components/icons'
import { useConfirm } from '../components/ConfirmDialog'
import SlidePanel from '../components/SlidePanel'
import SortableTh from '../components/SortableTh'
import StatusBadge from '../components/StatusBadge'
import {
  ChipGroup,
  ClearFilters,
  ResultCount,
  SearchInput,
  SelectFilter,
  ToggleChip,
  hasActiveFilters,
} from '../components/filters'
import { APPLICATION_STATUSES, OPPORTUNITY_TYPES, api } from '../api'
import { deadlineTone, formatDate, formatDateTime, formatScore, scoreTone, titleCase } from '../format'

const TABLE_COLUMNS = [
  { column: 'relevance_score', label: 'Score' },
  { column: 'title', label: 'Title' },
  { column: 'organization', label: 'Organization' },
  { column: 'status', label: 'Status' },
  { column: 'deadline', label: 'Deadline' },
  { column: 'date_bookmarked', label: 'Bookmarked' },
  { column: 'date_applied', label: 'Applied' },
  { column: 'last_updated', label: 'Updated' },
]

const BOARD_SORTS = [
  { value: 'last_updated', label: 'Sort: last updated' },
  { value: 'relevance_score', label: 'Sort: relevance' },
  { value: 'deadline', label: 'Sort: deadline' },
  { value: 'title', label: 'Sort: title' },
  { value: 'organization', label: 'Sort: organization' },
]

function ApplicationFilterBar({ filters, onChange, view, resultCount }) {
  const set = (patch) => onChange({ ...filters, ...patch })
  return (
    <div className="space-y-3 pb-4">
      <ChipGroup
        label="Type"
        options={OPPORTUNITY_TYPES}
        selected={filters.type || []}
        onChange={(type) => set({ type })}
      />
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          value={filters.search}
          onChange={(search) => set({ search })}
          placeholder="Search title, org, notes, contacts…"
        />
        <SelectFilter
          value={(filters.status || [])[0]}
          onChange={(status) => set({ status: status ? [status] : undefined })}
          options={APPLICATION_STATUSES.map((status) => ({ value: status, label: titleCase(status) }))}
          placeholder="Any status"
        />
        <ToggleChip
          active={Boolean(filters.strong_match)}
          onClick={() => set({ strong_match: filters.strong_match ? undefined : true })}
        >
          <StarIcon />
          Strong match
        </ToggleChip>
        <ToggleChip
          active={filters.deadline_within_days === 14}
          onClick={() => set({ deadline_within_days: filters.deadline_within_days === 14 ? undefined : 14 })}
          title="Deadline inside two weeks"
        >
          Closing soon
        </ToggleChip>
        {view === 'board' ? (
          <SelectFilter
            value={filters.sort}
            onChange={(sort) => set({ sort: sort || 'last_updated' })}
            options={BOARD_SORTS}
          />
        ) : null}
        <ClearFilters
          show={hasActiveFilters(filters)}
          onClear={() => onChange({ sort: filters.sort, order: filters.order })}
        />
        <ResultCount count={resultCount} noun="application" />
      </div>
    </div>
  )
}

// The pipeline reads left to right; the three terminal states sit at the end.
const COLUMNS = [
  { status: 'bookmarked', label: 'Bookmarked' },
  { status: 'planning_to_apply', label: 'Planning' },
  { status: 'applied', label: 'Applied' },
  { status: 'assessment', label: 'Assessment' },
  { status: 'interview', label: 'Interview' },
  { status: 'offer', label: 'Offer' },
  { status: 'rejected', label: 'Rejected' },
  { status: 'withdrawn', label: 'Withdrawn' },
]

function Card({ application, onOpen, onDragStart }) {
  const opportunity = application.opportunity || {}
  const deadline = application.deadline_override || opportunity.deadline
  return (
    <article
      draggable
      onDragStart={onDragStart}
      onClick={onOpen}
      className="cursor-pointer rounded border border-outline-variant bg-surface-container px-3 py-2 transition-colors hover:border-primary/60"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 text-on-surface">{opportunity.title || `Opportunity ${application.opportunity_id}`}</span>
        <span className={`shrink-0 font-mono font-medium ${scoreTone(opportunity.relevance_score)}`}>
          {formatScore(opportunity.relevance_score)}
        </span>
      </div>
      <div className="mt-1 line-clamp-1 text-on-surface-variant">{opportunity.organization}</div>
      <div className={`mt-2 font-mono text-data ${deadlineTone(deadline)}`}>
        {deadline ? `Due ${formatDate(deadline)}` : 'No deadline'}
      </div>
    </article>
  )
}

function ContactEditor({ contacts, onChange }) {
  const update = (index, field, value) => {
    const next = contacts.map((contact, position) =>
      position === index ? { ...contact, [field]: value } : contact,
    )
    onChange(next)
  }

  return (
    <div className="space-y-3">
      {contacts.map((contact, index) => (
        <div key={index} className="space-y-2 rounded border border-outline-variant p-3">
          <div className="grid grid-cols-2 gap-2">
            <input
              className="field"
              placeholder="Name"
              value={contact.name || ''}
              onChange={(event) => update(index, 'name', event.target.value)}
            />
            <input
              className="field"
              placeholder="Role"
              value={contact.role || ''}
              onChange={(event) => update(index, 'role', event.target.value)}
            />
          </div>
          <input
            className="field"
            placeholder="Email"
            value={contact.email || ''}
            onChange={(event) => update(index, 'email', event.target.value)}
          />
          <input
            className="field"
            placeholder="Notes"
            value={contact.notes || ''}
            onChange={(event) => update(index, 'notes', event.target.value)}
          />
          <button
            type="button"
            className="btn"
            onClick={() => onChange(contacts.filter((_, position) => position !== index))}
          >
            Remove contact
          </button>
        </div>
      ))}
      <button type="button" className="btn" onClick={() => onChange([...contacts, {}])}>
        Add contact
      </button>
    </div>
  )
}

export default function Applications({ onMutate }) {
  const [filters, setFilters] = useState({ sort: 'last_updated', order: 'desc' })
  const [view, setView] = useState('board')
  const [applications, setApplications] = useState([])
  const [selected, setSelected] = useState(null)
  const [draft, setDraft] = useState(null)
  const [dragId, setDragId] = useState(null)
  const [dragOver, setDragOver] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const confirm = useConfirm()

  const load = useCallback(async () => {
    try {
      setApplications(await api.applications(filters))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [filters])

  useEffect(() => {
    const timer = setTimeout(load, 200)
    return () => clearTimeout(timer)
  }, [load])

  const open = (application) => {
    setSelected(application)
    setDraft({
      status: application.status,
      notes: application.notes || '',
      cover_letter_notes: application.cover_letter_notes || '',
      deadline_override: application.deadline_override || '',
      contacts: application.contacts || [],
    })
  }

  const move = async (application, status) => {
    if (application.status === status) return
    try {
      await api.updateApplication(application.id, { status })
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
    }
  }

  const save = async () => {
    if (!selected || !draft) return
    setBusy(true)
    try {
      await api.updateApplication(selected.id, {
        ...draft,
        deadline_override: draft.deadline_override || null,
        contacts: draft.contacts.filter((contact) => contact.name || contact.email),
      })
      await load()
      setSelected(null)
      onMutate?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selected) return
    const confirmed = await confirm({
      key: 'delete-application',
      title: 'Remove this application from the pipeline?',
      body: (
        <>
          <span className="text-on-surface">{selected.opportunity?.title || 'This application'}</span> loses its
          status, dates, notes and contacts. The listing itself stays in Opportunities.
        </>
      ),
      confirmLabel: 'Remove',
    })
    if (!confirmed) return
    setBusy(true)
    try {
      await api.deleteApplication(selected.id)
      await load()
      setSelected(null)
      onMutate?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const closedCount = applications.filter((application) => application.status === 'closed').length

  return (
    <PageLayout
      title="Applications"
      description={`${applications.length} shown · ${
        view === 'board'
          ? 'drag a card between columns to change its status.'
          : 'click any column header to sort.'
      }`}
      error={error}
      scroll={view === 'table'}
      actions={
        <div className="flex rounded border border-outline-variant" role="group" aria-label="View">
          {[
            ['board', 'Board'],
            ['table', 'Table'],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setView(key)}
              aria-pressed={view === key}
              className={`px-3 py-1 font-mono text-data transition-colors ${
                view === key
                  ? 'bg-primary-container text-on-primary-container'
                  : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      }
      toolbar={
        <ApplicationFilterBar
          filters={filters}
          onChange={setFilters}
          view={view}
          resultCount={applications.length}
        />
      }
    >
      {view === 'board' ? (
      <div className="flex min-h-0 flex-1 gap-3 overflow-x-auto py-4">
        {COLUMNS.map((column) => {
          const items = applications.filter((application) => application.status === column.status)
          return (
            <section
              key={column.status}
              onDragOver={(event) => {
                event.preventDefault()
                setDragOver(column.status)
              }}
              onDragLeave={() => setDragOver((current) => (current === column.status ? null : current))}
              onDrop={(event) => {
                event.preventDefault()
                setDragOver(null)
                const application = applications.find((item) => item.id === dragId)
                if (application) move(application, column.status)
                setDragId(null)
              }}
              className={`flex min-w-[12rem] flex-1 flex-col rounded border transition-colors ${
                dragOver === column.status ? 'border-primary bg-primary/5' : 'border-outline-variant bg-surface'
              }`}
            >
              <header className="flex items-center justify-between border-b border-outline-variant px-3 py-2">
                <span className="label-data">{column.label}</span>
                <span className="font-mono text-data text-on-surface-variant">{items.length}</span>
              </header>
              <div className="flex-1 space-y-2 overflow-y-auto p-2">
                {items.map((application) => (
                  <Card
                    key={application.id}
                    application={application}
                    onOpen={() => open(application)}
                    onDragStart={() => setDragId(application.id)}
                  />
                ))}
                {items.length === 0 ? (
                  <div className="px-2 py-6 text-center font-mono text-data text-on-surface-variant">empty</div>
                ) : null}
              </div>
            </section>
          )
        })}
      </div>
      ) : (
      <div>
        <table className="w-full border-collapse">
          <thead>
            <tr className="text-left">
              {TABLE_COLUMNS.map((header) => (
                <SortableTh
                  key={header.column}
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
            {applications.map((application) => {
              const opportunity = application.opportunity || {}
              const deadline = application.deadline_override || opportunity.deadline
              return (
                <tr
                  key={application.id}
                  onClick={() => open(application)}
                  className={`cursor-pointer border-b border-outline-variant/60 transition-colors hover:bg-surface-container-high ${
                    opportunity.strong_match ? 'border-l-2 border-l-primary' : 'border-l-2 border-l-transparent'
                  }`}
                >
                  <td className={`px-3 py-2 font-mono font-medium ${scoreTone(opportunity.relevance_score)}`}>
                    {formatScore(opportunity.relevance_score)}
                  </td>
                  <td className="max-w-md px-3 py-2">
                    <span className="line-clamp-1 text-on-surface">{opportunity.title}</span>
                  </td>
                  <td className="max-w-[14rem] px-3 py-2">
                    <span className="line-clamp-1 text-on-surface-variant">{opportunity.organization}</span>
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge value={application.status} />
                  </td>
                  <td className={`whitespace-nowrap px-3 py-2 font-mono text-data ${deadlineTone(deadline)}`}>
                    {deadline ? formatDate(deadline) : '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-data text-on-surface-variant">
                    {formatDate(application.date_bookmarked)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-data text-on-surface-variant">
                    {application.date_applied ? formatDate(application.date_applied) : '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-data text-on-surface-variant">
                    {formatDate(application.last_updated)}
                  </td>
                </tr>
              )
            })}
            {applications.length === 0 && !error ? (
              <tr>
                <td colSpan={TABLE_COLUMNS.length} className="px-3 py-10 text-center text-on-surface-variant">
                  No applications match these filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      )}

      {closedCount ? (
        <p className="py-3 font-mono text-data text-on-surface-variant">
          {closedCount} closed application(s) hidden from the pipeline.
        </p>
      ) : null}

      <SlidePanel
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={selected?.opportunity?.title || 'Application'}
        subtitle={selected?.opportunity?.organization}
        footer={
          <div className="flex items-center gap-3">
            <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
            <button type="button" className="btn" onClick={() => setSelected(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn ml-auto hover:border-error hover:text-error"
              onClick={remove}
              disabled={busy}
            >
              Remove application
            </button>
          </div>
        }
      >
        {selected && draft ? (
          <div className="space-y-6">
            <div className="flex items-center gap-4">
              <div className="shrink-0 text-center">
                <div className={`font-mono text-2xl font-bold ${scoreTone(selected.opportunity?.relevance_score)}`}>
                  {formatScore(selected.opportunity?.relevance_score)}
                </div>
                <div className="label-data">/ 10</div>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-on-surface-variant">{selected.opportunity?.relevance_summary || 'No summary.'}</p>
                {selected.opportunity?.url ? (
                  <a
                    href={selected.opportunity.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-1 font-mono text-data text-primary hover:underline"
                  >
                    Open listing
                    <ExternalLinkIcon />
                  </a>
                ) : null}
              </div>
            </div>

            <div>
              <div className="label-data mb-2">Status</div>
              <div className="flex items-center gap-3">
                <Dropdown
                  className="w-56"
                  ariaLabel="Application status"
                  value={draft.status}
                  onChange={(status) => setDraft({ ...draft, status: status || draft.status })}
                  options={APPLICATION_STATUSES}
                />
                <StatusBadge value={draft.status} />
              </div>
            </div>

            <div>
              <div className="label-data mb-2">Status timeline</div>
              <ul className="space-y-1 font-mono text-data text-on-surface-variant">
                <li>Bookmarked · {formatDateTime(selected.date_bookmarked)}</li>
                <li>Applied · {selected.date_applied ? formatDateTime(selected.date_applied) : 'not yet'}</li>
                <li>Last updated · {formatDateTime(selected.last_updated)}</li>
              </ul>
            </div>

            <div>
              <div className="label-data mb-2">Deadline override</div>
              <input
                type="date"
                className="field w-auto"
                value={(draft.deadline_override || '').slice(0, 10)}
                onChange={(event) => setDraft({ ...draft, deadline_override: event.target.value })}
              />
              <p className="mt-1 font-mono text-data text-on-surface-variant">
                Listing deadline: {selected.opportunity?.deadline || 'none captured'}
              </p>
            </div>

            <div>
              <div className="label-data mb-2">Notes</div>
              <textarea
                className="field min-h-24"
                value={draft.notes}
                onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
                placeholder="Where you are with this application…"
              />
            </div>

            <div>
              <div className="label-data mb-2">Cover letter notes</div>
              <textarea
                className="field min-h-24"
                value={draft.cover_letter_notes}
                onChange={(event) => setDraft({ ...draft, cover_letter_notes: event.target.value })}
                placeholder="Angles to hit, projects to cite…"
              />
            </div>

            <div>
              <div className="label-data mb-2">Contacts</div>
              <ContactEditor
                contacts={draft.contacts}
                onChange={(contacts) => setDraft({ ...draft, contacts })}
              />
            </div>
          </div>
        ) : null}
      </SlidePanel>
    </PageLayout>
  )
}
