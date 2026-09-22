import { useCallback, useEffect, useState } from 'react'
import PageLayout from '../components/PageLayout'
import RoleAnalysisEditForm from '../components/RoleAnalysisEditForm'
import SortableTh from '../components/SortableTh'
import { AI_CALL_TITLE, AiSpark, EditIcon, StarIcon, StatusMark } from '../components/icons'
import { ChipGroup, SearchInput, SelectFilter, ToggleChip } from '../components/filters'
import { EXPERIENCE_LEVELS, OPPORTUNITY_TYPES, api } from '../api'
import { formatDateTime, titleCase } from '../format'

const STATUS_TONE = {
  met: 'border-primary/60 bg-primary/10 text-primary',
  partial: 'border-tertiary/60 bg-tertiary/10 text-tertiary',
  gap: 'border-error/60 bg-error/10 text-error',
  unknown: 'border-outline-variant text-on-surface-variant',
}
const PRIORITY_TONE = {
  high: 'border-primary text-primary',
  medium: 'border-tertiary/70 text-tertiary',
  low: 'border-outline-variant text-on-surface-variant',
}
const STATUS_RANK = { gap: 0, partial: 1, unknown: 2, met: 3 }
const PRIORITY_RANK = { high: 0, medium: 1, low: 2 }

function Section({ title, count, children }) {
  return (
    <section className="space-y-3">
      <h2>
        {title}
        {count !== undefined ? <span className="ml-2 font-mono text-data text-on-surface-variant">{count}</span> : null}
      </h2>
      {children}
    </section>
  )
}

export default function Insights() {
  const [analysis, setAnalysis] = useState(null)
  const [scope, setScope] = useState({ limit: 25 })
  const [reqSort, setReqSort] = useState({ sort: 'status', order: 'asc' })
  const [skillSort, setSkillSort] = useState({ sort: 'priority', order: 'asc' })
  const [statusFilter, setStatusFilter] = useState(undefined)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setAnalysis(await api.roleAnalysis())
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const generate = async () => {
    setGenerating(true)
    setError(null)
    try {
      setAnalysis(await api.generateRoleAnalysis(scope))
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  const saveEdits = async (changes) => {
    setSaving(true)
    setEditError(null)
    try {
      setAnalysis(await api.updateRoleAnalysis(analysis.id, changes))
      setEditing(false)
    } catch (err) {
      setEditError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const sortRows = (rows, { sort, order }, ranks = {}) => {
    const dir = order === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = ranks[sort] ? ranks[sort][a[sort]] ?? 99 : a[sort]
      const bv = ranks[sort] ? ranks[sort][b[sort]] ?? 99 : b[sort]
      if (av === bv) return 0
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      return av > bv ? dir : -dir
    })
  }

  const requirements = analysis
    ? sortRows(
        analysis.requirements.filter((item) => !statusFilter || item.status === statusFilter),
        reqSort,
        { status: STATUS_RANK },
      )
    : []
  const skills = analysis
    ? sortRows(analysis.recommended_skills, skillSort, { priority: PRIORITY_RANK })
    : []

  const coverage = analysis
    ? analysis.requirements.reduce((acc, item) => {
        acc[item.status] = (acc[item.status] || 0) + 1
        return acc
      }, {})
    : {}

  return (
    <PageLayout
      title="Role analysis"
      description="What these roles require, what your resume covers, what to learn next."
      contentClassName="pb-8"
    >
      {editing ? null : (
      <section className="my-6 max-w-6xl space-y-3 rounded border border-outline-variant bg-surface-container p-4">
        <div className="label-data block">Scope of the analysis</div>
        <ChipGroup
          options={OPPORTUNITY_TYPES}
          selected={scope.type || []}
          onChange={(type) => setScope({ ...scope, type })}
        />
        <div className="flex flex-wrap items-center gap-3">
          <SearchInput
            value={scope.search}
            onChange={(search) => setScope({ ...scope, search })}
            placeholder="Limit to listings matching…"
          />
          <SelectFilter
            value={(scope.experience_level || [])[0]}
            onChange={(level) => setScope({ ...scope, experience_level: level ? [level] : undefined })}
            options={EXPERIENCE_LEVELS}
            placeholder="All levels"
          />
          <ToggleChip
            active={Boolean(scope.strong_match)}
            onClick={() => setScope({ ...scope, strong_match: scope.strong_match ? undefined : true })}
          >
            <StarIcon />
            Strong matches only
          </ToggleChip>
          <label className="flex items-center gap-2">
            <span className="label-data">Listings</span>
            <input
              type="number"
              min="1"
              max="40"
              className="field w-20 font-mono"
              value={scope.limit}
              onChange={(event) => setScope({ ...scope, limit: Number(event.target.value) })}
            />
          </label>
          <button
            type="button"
            className="btn btn-primary"
            title={AI_CALL_TITLE}
            disabled={generating}
            onClick={generate}
          >
            <AiSpark />
            {generating ? 'Analyzing…' : analysis ? 'Re-analyze' : 'Analyze opportunities'}
          </button>
        </div>
        {generating ? (
          <p className="font-mono text-data text-tertiary">
            Reading every listing against your resume — one to three minutes.
          </p>
        ) : null}
        {error ? (
          <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{error}</p>
        ) : null}
      </section>
      )}

      {loading ? <p className="font-mono text-data text-on-surface-variant">Loading…</p> : null}

      {!loading && !analysis ? (
        <p className="max-w-6xl rounded border border-outline-variant bg-surface-container px-4 py-10 text-center text-on-surface-variant">
          No analysis yet. Pick a scope above and run it: Claude groups the roles, lists what they
          require, checks each against your resume, and recommends skills to build.
        </p>
      ) : null}

      {analysis && editing ? (
        <div className="pt-6">
          <RoleAnalysisEditForm
            key={analysis.id}
            analysis={analysis}
            onSave={saveEdits}
            onCancel={() => {
              setEditError(null)
              setEditing(false)
            }}
            busy={saving}
            error={editError}
          />
        </div>
      ) : null}

      {analysis && !editing ? (
        <div className="max-w-6xl space-y-8 pb-8">
          <div className="rounded border border-outline-variant bg-surface-container p-4">
            <div className="mb-2 flex flex-wrap items-center gap-3 font-mono text-data text-on-surface-variant">
              <span>{analysis.opportunity_count} listings</span>
              <span>·</span>
              <span>{analysis.scope}</span>
              <span>·</span>
              <span>{formatDateTime(analysis.generated_at)}</span>
              {analysis.resume_filename ? <span>· vs {analysis.resume_filename}</span> : null}
              {analysis.edited_at ? (
                <span className="text-tertiary">· edited by hand {formatDateTime(analysis.edited_at)}</span>
              ) : null}
              <button
                type="button"
                className="btn ml-auto"
                onClick={() => {
                  setEditError(null)
                  setEditing(true)
                }}
                title="Correct this analysis by hand"
              >
                <EditIcon />
                Edit
              </button>
            </div>
            <p className="whitespace-pre-line text-on-surface">{analysis.summary}</p>
          </div>

          {analysis.strengths.length ? (
            <Section title="Your differentiating strengths" count={analysis.strengths.length}>
              <ul className="grid gap-2 md:grid-cols-2">
                {analysis.strengths.map((strength, index) => (
                  <li key={index} className="rounded border border-primary/40 bg-primary/5 px-3 py-2 text-on-surface">
                    {strength}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {analysis.role_groups.length ? (
            <Section title="Role groups" count={analysis.role_groups.length}>
              <div className="grid gap-3 md:grid-cols-2">
                {analysis.role_groups.map((group) => (
                  <article key={group.label} className="rounded border border-outline-variant bg-surface-container p-4">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-on-surface">{group.label}</h3>
                      <span className="shrink-0 font-mono text-data text-primary">{group.count}</span>
                    </div>
                    <p className="mt-2 text-on-surface-variant">{group.description}</p>
                    {group.example_titles.length ? (
                      <ul className="mt-2 space-y-1">
                        {group.example_titles.map((title) => (
                          <li key={title} className="truncate font-mono text-data text-on-surface-variant">
                            · {title}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </article>
                ))}
              </div>
            </Section>
          ) : null}

          <Section title="Requirement coverage" count={analysis.requirements.length}>
            <div className="flex flex-wrap items-center gap-2">
              {['met', 'partial', 'gap'].map((status) =>
                coverage[status] ? (
                  <ToggleChip
                    key={status}
                    active={statusFilter === status}
                    onClick={() => setStatusFilter(statusFilter === status ? undefined : status)}
                  >
                    <StatusMark status={status} />
                    {coverage[status]} {status}
                  </ToggleChip>
                ) : null,
              )}
              {statusFilter ? (
                <button type="button" className="btn" onClick={() => setStatusFilter(undefined)}>
                  Show all
                </button>
              ) : null}
            </div>

            <table className="w-full table-fixed border-collapse">
              <colgroup>
                <col className="w-24" />
                <col className="w-[30%]" />
                <col className="w-[20%]" />
                <col />
              </colgroup>
              <thead>
                <tr className="text-left">
                  {[
                    { column: 'status', label: 'Status' },
                    { column: 'requirement', label: 'Requirement' },
                    { column: 'frequency', label: 'How often' },
                    { column: null, label: 'Your evidence / gap' },
                  ].map((header, index) => (
                    <SortableTh
                      key={header.column || index}
                      {...header}
                      sticky
                      sort={reqSort.sort}
                      order={reqSort.order}
                      onSort={(sort, order) => setReqSort({ sort, order })}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {requirements.map((item, index) => (
                  <tr key={index} className="border-b border-outline-variant/60 align-top">
                    <td className="px-3 py-3">
                      <span
                        className={`inline-flex h-5 w-5 items-center justify-center rounded border ${
                          STATUS_TONE[item.status]
                        }`}
                        title={titleCase(item.status)}
                      >
                        <StatusMark status={item.status} />
                      </span>
                    </td>
                    <td className="break-words px-3 py-3 text-on-surface">{item.requirement}</td>
                    <td className="break-words px-3 py-3 font-mono text-data text-on-surface-variant">{item.frequency || '—'}</td>
                    <td className="break-words px-3 py-3 text-on-surface-variant">
                      {item.evidence}
                      {item.gap_note ? (
                        <div className="mt-1 text-tertiary">Gap: {item.gap_note}</div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Recommended skills" count={skills.length}>
            <table className="w-full table-fixed border-collapse">
              <colgroup>
                <col className="w-24" />
                <col className="w-[22%]" />
                <col className="w-[27%]" />
                <col className="w-[19%]" />
                <col className="w-[16%]" />
              </colgroup>
              <thead>
                <tr className="text-left">
                  {[
                    { column: 'priority', label: 'Priority' },
                    { column: 'skill', label: 'Skill' },
                    { column: null, label: 'Why it matters' },
                    { column: null, label: 'Unlocks' },
                    { column: 'effort', label: 'Effort' },
                  ].map((header, index) => (
                    <SortableTh
                      key={header.column || index}
                      {...header}
                      sticky
                      sort={skillSort.sort}
                      order={skillSort.order}
                      onSort={(sort, order) => setSkillSort({ sort, order })}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {skills.map((item, index) => (
                  <tr key={index} className="border-b border-outline-variant/60 align-top">
                    <td className="px-3 py-3">
                      <span className={`rounded border px-2 py-[1px] font-mono text-data ${PRIORITY_TONE[item.priority]}`}>
                        {item.priority}
                      </span>
                    </td>
                    <td className="break-words px-3 py-3 text-on-surface">{item.skill}</td>
                    <td className="break-words px-3 py-3 text-on-surface-variant">{item.why}</td>
                    <td className="break-words px-3 py-3 text-on-surface-variant">{item.unlocks}</td>
                    <td className="break-words px-3 py-3 font-mono text-data text-on-surface-variant">{item.effort || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      ) : null}
    </PageLayout>
  )
}
