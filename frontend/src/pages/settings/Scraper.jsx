import { useEffect, useState } from 'react'
import { AI_CALL_TITLE, AiSpark } from '../../components/icons'
import { api } from '../../api'
import { formatDateTime, relativeTime } from '../../format'

export default function Scraper({ settings, status, setStatus, busy, act, onMutate }) {
  const [cron, setCron] = useState('')
  const [log, setLog] = useState([])

  useEffect(() => {
    if (settings?.cron_schedule) setCron(settings.cron_schedule)
  }, [settings?.cron_schedule])

  // Poll the log tail while a scrape runs so progress is visible live. Only this
  // page polls; the other sections have nothing to watch.
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const tail = await api.scrapeLogTail()
        if (cancelled) return
        setLog(tail.lines)
        const next = await api.scrapeStatus()
        if (cancelled) return
        setStatus(next)
        if (!next.running) onMutate?.()
      } catch {
        /* ignore transient polling errors */
      }
    }
    tick()
    const timer = setInterval(tick, status?.running ? 2000 : 15_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [status?.running, setStatus, onMutate])

  const summary = status?.last_summary

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1">
          <span className="label-data block">Schedule</span>
          <input
            className="field w-56 font-mono"
            value={cron}
            onChange={(event) => setCron(event.target.value)}
            placeholder="0 8,18 * * *"
          />
          <span className="block font-mono text-data text-on-surface-variant">
            Five-field cron, local time
          </span>
        </label>
        <button
          type="button"
          className="btn"
          disabled={busy || cron === settings?.cron_schedule}
          onClick={() => act(() => api.updateSettings({ cron_schedule: cron }), 'Schedule updated.')}
        >
          Save
        </button>
        <div className="ml-auto text-right font-mono text-data text-on-surface-variant">
          <div>last run {relativeTime(status?.last_run)}</div>
          <div>next run {formatDateTime(status?.next_run)}</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="btn btn-primary"
          title={`${AI_CALL_TITLE} — every listing found is classified by Claude`}
          disabled={busy || status?.running}
          onClick={() => act(() => api.runScrape(), 'Scrape started.')}
        >
          <AiSpark />
          {status?.running ? 'Running…' : 'Run now'}
        </button>
        {summary ? (
          <span className="font-mono text-data text-on-surface-variant">
            {summary.sources_scraped} sources ·{' '}
            <span className="text-primary">{summary.new_opportunities} new</span> ·{' '}
            <span className={summary.dead_links_skipped ? 'text-tertiary' : ''}>
              {summary.dead_links_skipped ?? 0} dead
            </span>{' '}
            ·{' '}
            <span className={summary.errors ? 'text-error' : ''}>{summary.errors} errors</span>
          </span>
        ) : null}
      </div>

      <div>
        <div className="label-data mb-2">Progress log</div>
        <pre className="max-h-80 overflow-auto rounded border border-outline-variant bg-surface p-3 font-mono text-data leading-relaxed text-on-surface-variant">
          {log.length ? log.join('\n') : 'No scrape has run in this session yet.'}
        </pre>
      </div>
    </div>
  )
}
