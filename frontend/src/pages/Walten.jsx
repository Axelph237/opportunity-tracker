import { useCallback, useEffect, useRef, useState } from 'react'
import Dropdown from '../components/Dropdown'
import Popover from '../components/Popover'
import Tooltip from '../components/Tooltip'
import PageLayout from '../components/PageLayout'
import { useConfirm } from '../components/ConfirmDialog'
import {
  AI_CALL_TITLE,
  AgentIcon,
  AttachIcon,
  CheckIcon,
  PlusIcon,
  BackIcon,
  ChevronIcon,
  LinkIcon,
  ModeIcon,
  SendIcon,
  ToolIcon,
  TrashIcon,
  UndoIcon,
} from '../components/icons'
import { WALTEN_MODELS, WALTEN_MODES, WALTEN_PRESETS, api } from '../api'
import { formatDateTime } from '../format'

const money = (value) => (value == null ? null : `$${value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`)
const seconds = (ms) => (ms == null ? null : `${(ms / 1000).toFixed(1)}s`)

/** Expandable record of every tool the agent used in a turn. */
function AuditLog({ calls }) {
  const [open, setOpen] = useState(false)
  if (!calls?.length) return null
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="label-data inline-flex items-center gap-1.5 transition-colors hover:text-primary"
      >
        <ToolIcon />
        {calls.length} tool {calls.length === 1 ? 'call' : 'calls'}
        <span aria-hidden="true">{open ? '−' : '+'}</span>
      </button>
      {open ? (
        <ul className="mt-2 space-y-1 rounded border border-outline-variant bg-surface p-2">
          {calls.map((call, index) => (
            <li key={index} className="flex gap-2 font-mono text-data">
              <span className="shrink-0 text-primary">{call.tool}</span>
              <span className="min-w-0 break-all text-on-surface-variant">{call.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/**
 * The rewind arrow on a message you sent.
 *
 * Sending commits the project first, so every message is a point the files can
 * be put back to. When there is nothing to put back the arrow still appears —
 * a control that silently vanishes gives no reason — but it drops its hover
 * treatment and explains itself instead.
 */
function UndoArrow({ message, onUndo, disabled }) {
  const live = message.can_undo && !disabled
  const label = live
    ? 'Undo changes'
    : message.snapshot_sha
      ? 'No changes to undo'
      : 'No restore points'

  return (
    // The positioning lives out here: Tooltip's own wrapper must stay
    // `relative` so the bubble hangs off the arrow.
    <span className="absolute -right-1 -top-3 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
      {/* Above the arrow and right-aligned to it: centred would run past the
          transcript's right edge, and to the side it would cover the message. */}
      <Tooltip label={label} placement="top-end">
        <button
          type="button"
          aria-label={label}
          // Not `disabled`: a disabled button is skipped by hover and focus in
          // some browsers, and the tooltip is the whole point of the inert state.
          aria-disabled={!live}
          onClick={live ? onUndo : undefined}
          className={`rounded-full border border-outline-variant bg-surface-container p-1.5 shadow-sm transition-colors ${
            live
              ? 'text-on-surface-variant hover:border-primary hover:bg-surface-container-high hover:text-on-surface'
              : 'text-outline'
          }`}
        >
          <UndoIcon className="h-3.5 w-3.5" />
        </button>
      </Tooltip>
    </span>
  )
}

function Turn({ message, agentName, agentIcon, onApprove, onReject, onUndo, busy }) {
  const isUser = message.role === 'user'

  // A conversation reads as two columns: you on the right, Walten on the left,
  // each leaving a margin on the far side so the sides stay distinguishable.
  if (isUser) {
    return (
      <div className="group flex justify-end pl-12">
        <div className="relative max-w-[42rem]">
          <p className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-secondary-container px-4 py-2.5 text-on-secondary-container">
            {message.content}
          </p>
          <UndoArrow message={message} onUndo={onUndo} disabled={busy} />
        </div>
      </div>
    )
  }

  const meta = [
    message.phase === 'apply' ? 'applied' : null,
    // money(message.cost_usd),
    seconds(message.duration_ms),
  ].filter(Boolean)

  return (
    <div className="flex justify-start pr-12">
      <article className="min-w-0 max-w-[46rem] space-y-2 rounded-2xl rounded-bl-md bg-surface-container-high px-4 py-3">
        <div className="flex items-center gap-2">
          <AgentIcon name={agentIcon} className="h-4 w-4 text-on-surface-variant" />
          <span className="label-data">{agentName}</span>
          {meta.length ? (
            <span className="font-mono text-data text-on-surface-variant">{meta.join(' · ')}</span>
          ) : null}
        </div>

        {message.error ? (
          <p className="rounded border border-error/60 bg-error/10 px-3 py-2 text-error">{message.error}</p>
        ) : null}

        {message.content ? (
          <p className="whitespace-pre-wrap break-words leading-relaxed text-on-surface">
            {message.content}
          </p>
        ) : null}

        <AuditLog calls={message.tool_calls} />

        {message.needs_approval && !message.resolved ? (
          <div className="space-y-2 rounded-lg border border-tertiary/50 bg-tertiary/10 px-4 py-3">
            <p className="text-tertiary">
              Nothing has changed yet. Approve to let it carry out exactly what it described.
            </p>
            <div className="flex gap-2">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={onApprove}>
                <CheckIcon />
                Approve
              </button>
              <button type="button" className="btn" disabled={busy} onClick={onReject}>
                Reject
              </button>
            </div>
          </div>
        ) : null}
      </article>
    </div>
  )
}

function ContextMenu({ session, onChange, onAttach, close }) {
  // Pick what kind of context first, then fill in that one thing. Showing a URL
  // field and an upload button side by side asked the question and answered it
  // at the same time.
  const [view, setView] = useState('menu')
  const [entry, setEntry] = useState('')
  const fileInput = useRef(null)
  const attached = [...session.context_files, ...session.context_urls]

  const addUrl = () => {
    const value = entry.trim()
    if (!value) return
    const key = /^https?:\/\//i.test(value) ? 'context_urls' : 'context_files'
    onChange({ [key]: [...new Set([...session[key], value])] })
    setEntry('')
    close()
  }

  const Choice = ({ icon, label, onClick }) => (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-md px-2 py-2.5 text-left transition-colors hover:bg-surface-container-high"
    >
      <span className="flex w-5 shrink-0 justify-center text-on-surface-variant">{icon}</span>
      <span className="flex-1 text-on-surface">{label}</span>
      <ChevronIcon className="h-3.5 w-3.5 shrink-0 text-on-surface-variant" />
    </button>
  )

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 px-2 pb-1 pt-0.5">
        {view !== 'menu' ? (
          <button
            type="button"
            aria-label="Back"
            className="text-on-surface-variant transition-colors hover:text-on-surface"
            onClick={() => setView('menu')}
          >
            <BackIcon className="h-3.5 w-3.5" />
          </button>
        ) : null}
        <span className="label-data">{view === 'url' ? 'Add a URL' : 'Context'}</span>
      </div>

      {view === 'menu' ? (
        <>
          <Choice
            icon={<AttachIcon />}
            label="Upload a file"
            onClick={() => fileInput.current?.click()}
          />
          <Choice icon={<LinkIcon />} label="Add a URL or path" onClick={() => setView('url')} />
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) {
                onAttach(file)
                close()
              }
              if (fileInput.current) fileInput.current.value = ''
            }}
          />
        </>
      ) : (
        <div className="space-y-2 px-1 pb-1">
          <input
            autoFocus
            className="field"
            placeholder="https://… or backend/scraper.py"
            value={entry}
            onChange={(event) => setEntry(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              event.preventDefault()
              addUrl()
            }}
          />
          <button type="button" className="btn btn-primary w-full justify-center" onClick={addUrl} disabled={!entry.trim()}>
            Add
          </button>
        </div>
      )}

      {attached.length ? (
        <ul className="space-y-1 border-t border-outline-variant px-1 pt-2">
          {attached.map((item) => (
            <li key={item} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate font-mono text-data text-on-surface-variant" title={item}>
                {item}
              </span>
              <button
                type="button"
                aria-label={`Remove ${item}`}
                className="shrink-0 text-on-surface-variant transition-colors hover:text-error"
                onClick={() =>
                  onChange({
                    context_files: session.context_files.filter((f) => f !== item),
                    context_urls: session.context_urls.filter((u) => u !== item),
                  })
                }
              >
                <TrashIcon className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export default function Walten() {
  const [overview, setOverview] = useState(null)
  const [session, setSession] = useState(null)
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const confirm = useConfirm()
  const bottom = useRef(null)

  const loadOverview = useCallback(async () => {
    try {
      const next = await api.walten()
      setOverview(next)
      return next
    } catch (err) {
      setError(err.message)
      return null
    }
  }, [])

  const messages = session?.messages || []
  const name = overview?.name || 'Walten'
  const agentIcon = overview?.icon || 'Dog'

  const loadSession = useCallback(async (id) => {
    try {
      setSession(await api.waltenSession(id))
    } catch (err) {
      setError(err.message)
    }
  }, [])

  /**
   * Start a conversation. `seed` carries the mode and model forward from the one
   * you were on.
   *
   * Untitled conversations get the time in their name once more than one exists.
   * They are all called "New session" until their first message renames them, and
   * two identical rows swapping highlight is what made creating one look like a
   * flicker.
   */
  const createSession = useCallback(async (seed = {}, siblings = []) => {
    // Number them rather than timestamp them: several created in the same minute
    // would otherwise share a title, which is the confusion this avoids.
    const used = siblings
      .map((item) => /^New session(?: (\d+))?$/.exec(item.title))
      .filter(Boolean)
      .map((match) => Number(match[1] || 1))
    const next = used.length ? Math.max(...used) + 1 : 1
    const title = next === 1 ? 'New session' : `New session ${next}`
    const created = await api.createWaltenSession({
      title,
      mode: seed.mode || 'assistant',
      model: seed.model || 'sonnet',
    })
    // Commit the list and the selection together, so there is never a frame
    // where the new row is missing from the sidebar and nothing is highlighted.
    setOverview(await api.walten())
    setSession(created)
    return created
  }, [])

  // Open the most recent conversation, or start one so the mode, model and
  // context controls are there to configure before the first message.
  useEffect(() => {
    let cancelled = false
    loadOverview().then(async (next) => {
      if (cancelled || !next) return
      if (next.sessions.length) {
        loadSession(next.sessions[0].id)
        return
      }
      try {
        if (!cancelled) await createSession()
      } catch (err) {
        setError(err.message)
      }
    })
    return () => {
      cancelled = true
    }
  }, [loadOverview, loadSession, createSession])

  /*
   * Poll while a turn is in flight so tool calls and the reply appear as they land.
   *
   * `pending` is needed as well as `running`: the POST that starts a turn returns
   * before FastAPI runs the background task, so the response it hands back still
   * says running=false. Without this the UI would never start polling and the
   * reply would only appear on a manual refresh.
   */
  useEffect(() => {
    if (!session?.id || (!session.running && !pending)) return undefined
    const id = session.id
    let cancelled = false
    const timer = setInterval(async () => {
      try {
        const next = await api.waltenSession(id)
        // A poll for the conversation you just navigated away from can land
        // after the new one has loaded. Dropping it keeps the old transcript
        // from replacing the one on screen.
        if (cancelled) return
        setSession((current) => (current?.id === id ? next : current))
        const last = next.messages[next.messages.length - 1]
        if (!next.running && last?.role === 'assistant') setPending(false)
      } catch (err) {
        if (cancelled) return
        setPending(false)
        setError(err.message)
      }
    }, 1200)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [session?.running, session?.id, pending])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [session?.messages?.length, session?.running])

  const newSession = async () => {
    setBusy(true)
    try {
      await createSession(session || {}, overview?.sessions || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const send = async (text) => {
    const body = (text ?? prompt).trim()
    if (!body) return
    let target = session
    if (!target) {
      target = await api.createWaltenSession({ mode: 'assistant', model: 'sonnet' })
      setSession(target)
    }
    setBusy(true)
    setError(null)
    try {
      const [updated, next] = await Promise.all([
        api.sendWaltenMessage(target.id, body),
        api.walten(),
      ])
      setOverview(next)
      setSession(updated)
      setPending(true)
      setPrompt('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const act = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      setSession(await fn())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  /**
   * Put the files back to the checkpoint taken when `message` was sent.
   *
   * The preview is fetched first so the confirmation can name what will change:
   * "undo" on a whole project is only meaningful if you can see its blast radius.
   */
  const undoTo = async (message) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const preview = await api.waltenUndoPreview(session.id, message.id)
      if (!preview.can_undo) {
        setNotice(preview.error || 'Nothing has changed since that message.')
        return
      }

      const plural = preview.count === 1 ? 'file is' : 'files are'
      const after = preview.later_messages
      const trail =
        after === 0
          ? ''
          : after === 1
            ? ', undoing this message and the one after it'
            : `, undoing this message and the ${after} after it`
      const ok = await confirm({
        key: 'walten-undo',
        title: 'Undo back to this message?',
        confirmLabel: 'Undo changes',
        body: (
          <>
            <p>
              {preview.count} {plural} put back to how they were just before you sent it
              {trail}.
            </p>
            {preview.files.length ? (
              <ul className="mt-2 max-h-28 overflow-auto font-mono text-data">
                {preview.files.map((file) => (
                  <li key={file} className="truncate">
                    {file}
                  </li>
                ))}
                {preview.count > preview.files.length ? (
                  <li>…and {preview.count - preview.files.length} more</li>
                ) : null}
              </ul>
            ) : null}
            <p className="mt-2">
              Only files git tracks. Your database is untouched, so anything {name} sorted or
              tagged stays. The current state is committed first, so this is recoverable too.
            </p>
          </>
        ),
      })
      if (!ok) return

      const result = await api.undoWaltenMessage(session.id, message.id)
      setSession(await api.waltenSession(session.id))
      setNotice(`Restored ${result.count} file${result.count === 1 ? '' : 's'} to that point.`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const removeSession = async (target) => {
    const ok = await confirm({
      key: 'delete-walten-session',
      title: 'Delete this conversation?',
      body: <>“{target.title}” and its transcript are removed. Nothing it already did is undone.</>,
      confirmLabel: 'Delete',
    })
    if (!ok) return
    await api.deleteWaltenSession(target.id)
    const next = await loadOverview()
    if (next?.sessions?.length) {
      setSession(await api.waltenSession(next.sessions[0].id))
      return
    }
    // Deleting the last conversation must not leave the composer session-less:
    // its mode, model and attachment controls all hang off the current session.
    await createSession(session || {})
  }

  const attachedCount =
    (session?.context_files?.length || 0) + (session?.context_urls?.length || 0)
  const live = session?.live

  return (
    <PageLayout
      title={name}
      icon={<AgentIcon name={agentIcon} className="h-6 w-6 text-on-surface-variant" />}
      description="Runs tasks across your data, triggers scripts, and edits the app when you let it."
      error={error}
      banner={
        notice ? (
          <div className="mb-4 flex items-start gap-3 rounded border border-primary/50 bg-primary/10 px-4 py-2 text-on-surface">
            <span className="min-w-0 flex-1">{notice}</span>
            <button type="button" className="shrink-0 text-on-surface-variant hover:text-on-surface" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </div>
        ) : null
      }
      actions={
        overview && !overview.claude_cli ? (
          <span className="text-error">claude CLI not found</span>
        ) : null
      }
    >
      <div className="flex h-full min-h-0 gap-6 py-6">
        <aside className="w-56 shrink-0 space-y-1 overflow-auto">
          <div className="flex items-center justify-between gap-2 px-1 pb-2">
            <span className="label-data">Conversations</span>
            <button
              type="button"
              aria-label="New conversation"
              title="New conversation"
              className="rounded p-1 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface disabled:opacity-45"
              onClick={newSession}
              disabled={busy}
            >
              <PlusIcon />
            </button>
          </div>
          {overview?.sessions?.length ? (
            overview.sessions.map((item) => (
              <div
                key={item.id}
                className={`group flex items-center gap-1 rounded border px-2 py-1.5 transition-colors ${
                  item.id === session?.id
                    ? 'border-primary bg-secondary-container text-on-secondary-container'
                    : 'border-transparent hover:bg-surface-container-high'
                }`}
              >
                <button
                  type="button"
                  onClick={() => loadSession(item.id)}
                  className="min-w-0 flex-1 truncate text-left"
                  title={item.title}
                >
                  {item.title}
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${item.title}`}
                  className="shrink-0 opacity-0 transition-opacity hover:text-error group-hover:opacity-100"
                  onClick={() => removeSession(item)}
                >
                  <TrashIcon className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          ) : (
            <p className="px-1 text-on-surface-variant">No conversations yet.</p>
          )}
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <div className="min-h-0 flex-1 space-y-6 overflow-auto pr-2 pt-14">
            {messages.length === 0 && !session?.running && !pending ? (
              <p className="max-w-[46rem] text-on-surface-variant">
                {name} works on this installation — its database, files and scripts. Every turn runs
                read-only first; anything that writes waits for your approval.
              </p>
            ) : null}

            {messages.map((message) => (
              <Turn
                key={message.id}
                message={message}
                agentName={name}
                agentIcon={agentIcon}
                busy={busy || session?.running || pending}
                onApprove={() => {
                  setPending(true)
                  act(() => api.approveWalten(session.id))
                }}
                onReject={() => act(() => api.rejectWalten(session.id))}
                onUndo={() => undoTo(message)}
              />
            ))}

            {session?.running || pending ? (
              /* Deliberately plain: a boxed panel listing every tool call drew
                 more attention than the reply it was waiting for. */
              <div className="flex items-center gap-3 py-1 text-on-surface-variant">
                <span className="dot-pulse flex items-center gap-1" aria-hidden="true">
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                </span>
                <span className="min-w-0 truncate font-mono text-data">
                  {live?.events?.length
                    ? `${live.events[live.events.length - 1].tool} · ${live.events[live.events.length - 1].detail}`
                    : live?.phase === 'apply'
                      ? 'Applying'
                      : 'Thinking'}
                </span>
                <span className="shrink-0 font-mono text-data">{seconds(live?.elapsed_ms)}</span>
                <button
                  type="button"
                  className="shrink-0 font-mono text-data underline-offset-2 transition-colors hover:text-on-surface hover:underline"
                  onClick={() => {
                    setPending(false)
                    act(() => api.stopWalten(session.id))
                  }}
                >
                  Stop
                </button>
              </div>
            ) : null}

            <div ref={bottom} />
          </div>

          {messages.length === 0 && !session?.running && !pending ? (
            <div className="flex flex-wrap gap-2">
              {WALTEN_PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  title={preset.prompt}
                  onClick={() => setPrompt(preset.prompt)}
                  className="rounded-full border border-outline-variant px-3 py-1 text-on-surface-variant transition-colors hover:border-primary hover:text-on-surface"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          ) : null}

          <form
            className="rounded-xl border border-outline-variant bg-surface-container-lowest shadow-sm transition-colors focus-within:border-primary"
            onSubmit={(event) => {
              event.preventDefault()
              send()
            }}
          >
            <textarea
              className="w-full resize-none bg-transparent px-4 pt-3.5 leading-relaxed text-on-surface outline-none placeholder:text-on-surface-variant"
              rows={2}
              placeholder={`Ask ${name} to do something…`}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault()
                  send()
                }
              }}
            />

            {/* Controls live on the composer's bottom edge rather than in a
                panel of their own, so the chat is the page and the options are
                one click away from where you type. */}
            {/* Two rows, like the reference composer: controls and send on one
                line, the model on its own line beneath at the bottom left. */}
            <div className="flex items-center gap-1 px-2.5 pt-1">
              {session ? (
                <>
                <Popover
                  label="Attach context"
                  icon={<AttachIcon />}
                  badge={attachedCount || null}
                  disabled={busy}
                >
                  {(close) => (
                    <ContextMenu
                      session={session}
                      close={close}
                      onChange={(patch) => act(() => api.updateWaltenSession(session.id, patch))}
                      onAttach={(file) => act(() => api.uploadWaltenContext(session.id, file))}
                    />
                  )}
                </Popover>

                <Dropdown
                  variant="inline"
                  className="w-auto"
                  ariaLabel="Mode"
                  value={session.mode}
                  onChange={(value) => act(() => api.updateWaltenSession(session.id, { mode: value || 'assistant' }))}
                  options={WALTEN_MODES.map((m) => ({
                    value: m.value,
                    label: m.label,
                    description: m.description,
                    icon: <ModeIcon mode={m.value} />,
                  }))}
                  panelClassName="w-[22rem]"
                  header="Modes"
                  hint={{ keys: ['↑', '↓'], text: 'to switch' }}
                />
                </>
              ) : null}

              <span className="ml-auto hidden items-center gap-2 font-mono text-data text-on-surface-variant sm:flex">
                {session?.mode === 'engineer' ? (
                  <span className="text-tertiary">can edit source</span>
                ) : null}
                <span>⌘↵</span>
              </span>

              <button
                type="submit"
                className="btn btn-primary"
                aria-label="Send"
                title={AI_CALL_TITLE}
                disabled={busy || session?.running || pending || !prompt.trim()}
              >
                <SendIcon />
              </button>
            </div>

            {session ? (
              <div className="flex px-2.5 pb-2.5 pt-1">
                <Dropdown
                  variant="inline"
                  className="w-auto text-data"
                  buttonClassName="rounded-full bg-surface-container-high px-2.5 py-0.5"
                  ariaLabel="Model"
                  value={session.model}
                  onChange={(value) => act(() => api.updateWaltenSession(session.id, { model: value || 'sonnet' }))}
                  options={WALTEN_MODELS}
                  panelClassName="w-[20rem] text-sm"
                  header="Models"
                  hint={{ keys: ['↑', '↓'], text: 'to switch' }}
                />
              </div>
            ) : null}
          </form>
        </div>
      </div>
    </PageLayout>
  )
}
