import { AI_CALL_TITLE, AiSpark, CheckIcon, SettingsIcon } from '../../components/icons'

/**
 * Step 5 — offer a first run. Both halves of it cost Claude calls and a few
 * minutes, so it is a choice rather than something that just happens.
 */
export default function SearchStep({ settings, resume, runInitialSearch, setRunInitialSearch }) {
  const ready = Boolean(settings?.claude_cli)

  const Option = ({ value, title, body, icon }) => (
    <button
      type="button"
      aria-pressed={runInitialSearch === value}
      disabled={value && !ready}
      onClick={() => setRunInitialSearch(value)}
      className={`flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors disabled:opacity-45 ${
        runInitialSearch === value
          ? 'border-primary bg-secondary-container text-on-secondary-container'
          : 'border-outline-variant hover:bg-surface-container-high'
      }`}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className="min-w-0">
        <span className="block text-on-surface">{title}</span>
        <span className="mt-1 block text-on-surface-variant">{body}</span>
      </span>
      {runInitialSearch === value ? <CheckIcon className="mt-1 shrink-0 text-primary" /> : null}
    </button>
  )

  return (
    <div className="space-y-4">
      <p className="text-on-surface-variant">
        The app ships with 20 starter sources. A first run scrapes them, scores what it finds
        against your resume, and asks Claude to suggest sources you are missing.
      </p>

      <Option
        value
        icon={<AiSpark className="h-5 w-5 text-primary" />}
        title="Run an initial search now"
        body="Scrapes every active source and proposes new ones. Takes a few minutes and runs in the background — you can use the app while it works."
      />
      <Option
        value={false}
        icon={<SettingsIcon name="scraper" className="h-5 w-5 text-on-surface-variant" />}
        title="Skip for now"
        body="Nothing runs. Start it later from Settings → Scraper, or let the schedule pick it up at 8am and 6pm."
      />

      {!ready ? (
        <p className="text-error">
          Claude Code was not found, so an initial search cannot run yet. Set the path in
          Settings → Claude and start one from Settings → Scraper.
        </p>
      ) : null}
      {runInitialSearch && !resume?.loaded ? (
        <p className="text-tertiary">
          No resume is loaded, so the scores from this run will be generic. You can re-score later
          by uploading one and running the scraper again.
        </p>
      ) : null}
      {runInitialSearch ? (
        <p className="font-mono text-data text-on-surface-variant" title={AI_CALL_TITLE}>
          This spends Claude calls: one per batch of listings, plus one web search pass.
        </p>
      ) : null}
    </div>
  )
}
