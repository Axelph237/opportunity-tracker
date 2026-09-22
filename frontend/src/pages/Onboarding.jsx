import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchStep from './onboarding/SearchStep'
import { AgentStep, ClaudeStep, ResumeStep, ThemeStep } from './onboarding/steps'
import { AgentIcon, BackIcon, CheckIcon } from '../components/icons'
import { api } from '../api'

const STEPS = [
  { key: 'claude', title: 'Connect Claude Code', subtitle: 'Step 1 of 5' },
  { key: 'theme', title: 'Choose your colours', subtitle: 'Step 2 of 5' },
  { key: 'agent', title: 'Name your agent', subtitle: 'Step 3 of 5' },
  { key: 'resume', title: 'Add your resume', subtitle: 'Step 4 of 5' },
  { key: 'search', title: 'First search', subtitle: 'Step 5 of 5' },
]

/**
 * First-run setup. Each answer is written to the real settings as it is made,
 * so quitting halfway still leaves the app configured up to that point.
 */
export default function Onboarding({ onDone }) {
  const navigate = useNavigate()
  const [index, setIndex] = useState(0)
  const [settings, setSettings] = useState(null)
  const [resume, setResume] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [runInitialSearch, setRunInitialSearch] = useState(true)

  const reload = useCallback(async () => {
    try {
      const [nextSettings, nextResume] = await Promise.all([api.settings(), api.resume()])
      setSettings(nextSettings)
      setResume(nextResume)
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  /** Save a setting immediately; the wizard has no separate commit. */
  const act = async (fn) => {
    setBusy(true)
    try {
      await fn()
      await reload()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const go = (nextIndex) => setIndex(nextIndex)

  const finish = async () => {
    setBusy(true)
    try {
      await api.updateSettings({ onboarding_complete: true })
      onDone?.()
      if (runInitialSearch && settings?.claude_cli) {
        // Fire and forget: both run in the background on the server.
        api.discoverSources({ count: 8 }).catch(() => {})
        api.runScrape().catch(() => {})
      }
      navigate(runInitialSearch ? '/settings/scraper' : '/opportunities', { replace: true })
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const stepProps = { settings, resume, act, reload, runInitialSearch, setRunInitialSearch }
  const renderStep = (position) => {
    switch (STEPS[position].key) {
      case 'claude':
        return <ClaudeStep {...stepProps} />
      case 'theme':
        return <ThemeStep {...stepProps} />
      case 'agent':
        return <AgentStep {...stepProps} />
      case 'resume':
        return <ResumeStep {...stepProps} />
      default:
        return <SearchStep {...stepProps} />
    }
  }

  const Panel = ({ position }) => (
    <div>
      <p className="label-data">{STEPS[position].subtitle}</p>
      <h1 className="mt-1">{STEPS[position].title}</h1>
      <div className="mt-6">{renderStep(position)}</div>
    </div>
  )

  const last = index === STEPS.length - 1

  return (
    <div className="flex h-full flex-col overflow-auto bg-surface">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col px-8 py-10">
        <div className="mb-8 flex items-center gap-3">
          <AgentIcon
            name={settings?.settings?.walten_icon || 'Dog'}
            className="h-5 w-5 text-on-surface-variant"
          />
          <span className="label-data">Opportunity Tracker · setup</span>
        </div>

        {error ? (
          <div className="mb-4 rounded border border-error/60 bg-error/10 px-4 py-2 text-error">{error}</div>
        ) : null}

        <div className="flex-1">
          <Panel position={index} />
        </div>

        <div className="mt-10 flex items-center gap-3 border-t border-outline-variant pt-5">
          <div className="flex gap-1.5" aria-hidden="true">
            {STEPS.map((step, position) => (
              <span
                key={step.key}
                className={`h-1.5 rounded-full transition-all ${
                  position === index ? 'w-6 bg-primary' : 'w-1.5 bg-outline-variant'
                }`}
              />
            ))}
          </div>

          {index > 0 ? (
            <button type="button" className="btn" onClick={() => go(index - 1)} disabled={busy}>
              <BackIcon />
              Back
            </button>
          ) : null}

          {/* An existing install should not have to walk five steps to get in. */}
          <button
            type="button"
            className="font-mono text-data text-on-surface-variant underline-offset-2 transition-colors hover:text-on-surface hover:underline"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await api.updateSettings({ onboarding_complete: true })
                onDone?.()
                navigate('/opportunities', { replace: true })
              } catch (err) {
                setError(err.message)
                setBusy(false)
              }
            }}
          >
            Skip setup
          </button>

          <button
            type="button"
            className="btn btn-primary ml-auto"
            disabled={busy}
            onClick={() => (last ? finish() : go(index + 1))}
          >
            {last ? (
              <>
                <CheckIcon />
                {runInitialSearch ? 'Finish and search' : 'Finish'}
              </>
            ) : (
              <>Next →</>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
