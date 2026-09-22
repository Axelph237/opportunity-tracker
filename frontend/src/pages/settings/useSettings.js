import { useCallback, useEffect, useState } from 'react'
import { api } from '../../api'

/**
 * Shared state for every settings page.
 *
 * Note for callers: `settings` is null on the first render, so any uncontrolled
 * input using `defaultValue` must also carry a `key` tied to the stored value.
 * Without it the field keeps whatever fallback it mounted with and never shows
 * what is actually saved.
 *
 * Each section is its own route, so each one loads what it needs rather than a
 * parent holding state for pages that are not on screen.
 */
export function useSettings(onMutate) {
  const [settings, setSettings] = useState(null)
  const [resume, setResume] = useState(null)
  const [status, setStatus] = useState(null)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [nextSettings, nextResume, nextStatus] = await Promise.all([
        api.settings(),
        api.resume(),
        api.scrapeStatus(),
      ])
      setSettings(nextSettings)
      setResume(nextResume)
      setStatus(nextStatus)
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  /** Run a mutation, surface the outcome, and refresh. */
  const act = async (fn, successMessage) => {
    setBusy(true)
    setMessage(null)
    setError(null)
    try {
      await fn()
      setMessage(successMessage)
      await load()
      onMutate?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return { settings, resume, status, setStatus, message, error, busy, act, load }
}
