import { EXPERIENCE_LEVELS, OPPORTUNITY_TYPES } from '../api'
import {
  ChipGroup,
  ClearFilters,
  RangeFilter,
  ResultCount,
  SearchInput,
  SelectFilter,
  ToggleChip,
  hasActiveFilters,
} from './filters'
import { StarIcon } from './icons'

/** Filter controls for the opportunities table. Reads and writes one filter object. */
export default function FilterBar({ filters, onChange, sources = [], resultCount }) {
  const set = (patch) => onChange({ ...filters, ...patch })

  return (
    <div className="space-y-3 pb-4">
      <div className="flex flex-wrap items-center gap-2">
        <ChipGroup
          label="Type"
          options={OPPORTUNITY_TYPES}
          selected={filters.type || []}
          onChange={(type) => set({ type })}
        />
        <span className="mx-1 h-4 w-px bg-outline-variant" aria-hidden="true" />
        <ToggleChip
          active={Boolean(filters.strong_match)}
          onClick={() => set({ strong_match: filters.strong_match ? undefined : true })}
          title="Only listings scored 7.5 or above"
        >
          <StarIcon />
          Strong match
        </ToggleChip>
        <ToggleChip
          active={Boolean(filters.remote)}
          onClick={() => set({ remote: filters.remote ? undefined : true })}
        >
          Remote
        </ToggleChip>
        <ToggleChip
          active={filters.deadline_within_days === 14}
          onClick={() => set({ deadline_within_days: filters.deadline_within_days === 14 ? undefined : 14 })}
          title="Deadline inside two weeks"
        >
          Closing soon
        </ToggleChip>
        <ToggleChip
          active={filters.has_advice === true}
          onClick={() => set({ has_advice: filters.has_advice === true ? undefined : true })}
          title="Listings with saved resume advice"
        >
          Has resume advice
        </ToggleChip>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          value={filters.search}
          onChange={(search) => set({ search })}
          placeholder="Search title, org, tags, skills…"
        />

        <SelectFilter
          value={filters.experience_level}
          onChange={(experience_level) => set({ experience_level })}
          options={EXPERIENCE_LEVELS}
          placeholder="All levels"
        />

        <SelectFilter
          value={filters.source_id}
          onChange={(source_id) => set({ source_id })}
          options={sources.map((source) => ({ value: source.id, label: source.name }))}
          placeholder="All sources"
          className="w-auto max-w-[16rem]"
        />

        <SelectFilter
          value={filters.status}
          onChange={(status) => set({ status })}
          options={[
            { value: 'none', label: 'Not tracked' },
            { value: 'bookmarked', label: 'Bookmarked' },
            { value: 'planning_to_apply', label: 'Planning to apply' },
            { value: 'applied', label: 'Applied' },
            { value: 'interview', label: 'Interview' },
            { value: 'offer', label: 'Offer' },
          ]}
          placeholder="Any tracking state"
        />

        <RangeFilter
          label="Score"
          min={filters.min_score}
          max={filters.max_score}
          onChange={({ min, max }) => set({ min_score: min, max_score: max })}
        />

        <ClearFilters
          show={hasActiveFilters(filters)}
          onClear={() => onChange({ sort: filters.sort, order: filters.order })}
        />

        <ResultCount count={resultCount} />
      </div>
    </div>
  )
}
