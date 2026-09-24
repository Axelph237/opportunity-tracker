import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import Applications from './pages/Applications'
import Insights from './pages/Insights'
import Onboarding from './pages/Onboarding'
import Opportunities from './pages/Opportunities'
import Resumes from './pages/Resumes'
import Settings from './pages/Settings'
import SettingsSection from './pages/settings/SettingsSection'
import Sources from './pages/Sources'
import Walten from './pages/Walten'
import Tooltip from './components/Tooltip'
import { ResizeHandle, usePanelSize } from './components/Resizable'
import { useDragReorder } from './components/reorder'
import { AgentIcon, ChevronIcon, NavIcon, OfflineIcon } from './components/icons'
import { ApiOfflineError, api } from './api'
import { formatDateTime, relativeTime } from './format'

const NAV = [
  { to: '/opportunities', label: 'Opportunities', icon: 'opportunities', badge: 'opportunities' },
  { to: '/applications', label: 'Applications', icon: 'applications', badge: 'applications' },
  { to: '/resumes', label: 'Resumes', icon: 'resumes', badge: 'resumes' },
  { to: '/insights', label: 'Role analysis', icon: 'insights' },
  { to: '/sources', label: 'Sources', icon: 'sources', badge: 'pending_proposals' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]

// The shipped order, and the identity the remembered one is reconciled
// against. Module scope on purpose: `useDragReorder` keeps callbacks keyed to
// this array, and rebuilding it each render would rebuild them too.
const NAV_ORDER = NAV.map((item) => item.to)
const NAV_BY_PATH = Object.fromEntries(NAV.map((item) => [item.to, item]))

// The sidebar is one resizable width rather than a width plus a collapsed
// flag. Drag it under the threshold and it becomes icons; the collapse button
// is a shortcut that drags it to the minimum for you. One source of truth, so
// the two controls can never disagree about which mode the bar is in.
const NAV_WIDTH = { min: 56, max: 360, default: 208 }
// Below this there is no room for a label beside an icon, so showing one
// produces a column of clipped words rather than a narrower sidebar.
const NAV_ICON_THRESHOLD = 140

/**
 * Icon-only items are square and centred; the active marker becomes a filled
 * tile rather than the left bar, which on a centred square would push the
 * icon off its own centre by the width of the border.
 */
const navLinkClass = (iconOnly) => ({ isActive }) =>
  iconOnly
    ? `mx-auto flex h-10 w-10 items-center justify-center rounded transition-colors ${
        isActive
          ? 'bg-secondary-container text-on-secondary-container'
          : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
      }`
    : `flex items-center gap-3 rounded py-2 pl-[10px] pr-3 transition-colors ${
        isActive
          ? 'border-l-2 border-primary bg-secondary-container text-on-secondary-container'
          : 'border-l-2 border-transparent text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
      }`

export default function App() {
  const [stats, setStats] = useState(null)
  const [status, setStatus] = useState(null)
  const [offline, setOffline] = useState(null)
  const [waltenName, setWaltenName] = useState('Walten')
  const [waltenIcon, setWaltenIcon] = useState('Dog')
  // null until the first stats call answers; avoids flashing the app then the wizard.
  const [onboarded, setOnboarded] = useState(null)
  // Read synchronously by usePanelSize, so a collapsed sidebar never expands
  // for a frame on load.
  const [navWidth, setNavWidth] = usePanelSize('nav', NAV_WIDTH.default, {
    min: NAV_WIDTH.min,
    max: NAV_WIDTH.max,
  })
  const navCollapsed = navWidth < NAV_ICON_THRESHOLD

  // Which sections, in which order. The agent link below is deliberately not
  // part of this: it is pinned to the bottom of the bar as its own thing, and
  // letting it drift into the middle of the list would lose that.
  const { order: navOrder, dragging, itemProps, moveBy } = useDragReorder('nav-order', NAV_ORDER)

  // Expanding should return the bar to the width it had, not to the default —
  // so remember the last width that was wide enough to count as expanded.
  const lastExpanded = useRef(navCollapsed ? NAV_WIDTH.default : navWidth)
  useEffect(() => {
    if (!navCollapsed) lastExpanded.current = navWidth
  }, [navWidth, navCollapsed])

  const toggleNav = useCallback(() => {
    setNavWidth(navCollapsed ? lastExpanded.current : NAV_WIDTH.min)
  }, [navCollapsed, setNavWidth])

  const refreshHeader = useCallback(async () => {
    try {
      const [nextStats, nextStatus] = await Promise.all([api.stats(), api.scrapeStatus()])
      setStats(nextStats)
      setStatus(nextStatus)
      setOffline(null)
      if (nextStats?.walten_name) setWaltenName(nextStats.walten_name)
      if (nextStats?.walten_icon) setWaltenIcon(nextStats.walten_icon)
      if (typeof nextStats?.onboarding_complete === 'boolean') setOnboarded(nextStats.onboarding_complete)
    } catch (error) {
      // A transient API error is not worth reporting, but an unreachable backend is:
      // every table would otherwise just show an error with no obvious cause.
      setOffline(error instanceof ApiOfflineError ? error.message : null)
    }
  }, [])

  useEffect(() => {
    refreshHeader()
    const timer = setInterval(refreshHeader, 20_000)
    return () => clearInterval(timer)
  }, [refreshHeader])

  // Nothing is rendered until we know, so a returning user never sees the wizard.
  if (onboarded === null) return <div className="h-screen bg-surface" />
  if (!onboarded) {
    return (
      <div className="h-screen bg-surface">
        <Onboarding
          onDone={() => {
            setOnboarded(true)
            refreshHeader()
          }}
        />
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* No right border: the resize handle below draws the dividing line, and
          two of them side by side reads as a seam. */}
      {/* Deliberately not `overflow-hidden`: the collapsed items hang their
          labels off the right edge as tooltips, and a clipping ancestor would
          cut every one of them off. Labels truncate instead. */}
      <nav
        aria-label="Main"
        className="flex h-full shrink-0 flex-col bg-surface-container"
        style={{ width: navWidth }}
      >
        <div className={`border-b border-outline-variant py-5 ${navCollapsed ? 'px-0 text-center' : 'px-5'}`}>
          {navCollapsed ? (
            <div className="font-mono text-data tracking-[0.1em] text-primary">OT</div>
          ) : (
            <>
              <div className="truncate font-mono text-data tracking-[0.2em] text-primary">OPPORTUNITY</div>
              <div className="truncate font-mono text-data tracking-[0.2em] text-on-surface-variant">
                TRACKER
              </div>
            </>
          )}
        </div>

        {/* Dragging is unreachable without a pointer, and nothing about a link
            announces that it can be moved, so both facts are stated once here
            rather than on every item. */}
        <p id="nav-reorder-hint" className="sr-only">
          Sections can be reordered: drag one into place, or focus it and press Alt with the up or
          down arrow key.
        </p>
        <ul
          aria-describedby="nav-reorder-hint"
          className={`space-y-1 py-3 ${navCollapsed ? 'px-0' : 'p-3'}`}
        >
          {navOrder.map((path) => NAV_BY_PATH[path]).map((item) => (
            <li
              key={item.to}
              {...itemProps(item.to)}
              // The item being dragged fades in place while the others shuffle
              // around it. The drag image the cursor carries was captured at
              // dragstart, so it stays solid.
              className={`rounded transition-opacity ${dragging === item.to ? 'opacity-40' : ''}`}
            >
              {/* Collapsed to icons, the label has to come back on hover or the
                  bar is a row of glyphs with nothing to identify them. */}
              <Tooltip
                label={navCollapsed ? item.label : ''}
                placement="right"
                className={navCollapsed ? 'w-full' : ''}
              >
                {/* Collapsed, the icon is all that is left on screen, so the
                    name has to come from the label rather than the text. */}
                <NavLink
                  to={item.to}
                  aria-label={navCollapsed ? item.label : undefined}
                  className={navLinkClass(navCollapsed)}
                  // Off, so the browser does not start its own drag of the URL
                  // and the enclosing item becomes the drag source instead.
                  draggable={false}
                  onKeyDown={(event) => {
                    // Alt-modified, because a bare arrow key on a focused link
                    // already means something: it scrolls, and it is how much
                    // assistive technology moves between elements.
                    if (!event.altKey) return
                    const delta = event.key === 'ArrowUp' ? -1 : event.key === 'ArrowDown' ? 1 : 0
                    if (delta && moveBy(item.to, delta)) event.preventDefault()
                  }}
                >
                  <NavIcon name={item.icon} />
                  {navCollapsed ? null : (
                    <>
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.badge && stats?.[item.badge] ? (
                        <span className="font-mono text-data opacity-80">{stats[item.badge]}</span>
                      ) : null}
                    </>
                  )}
                </NavLink>
              </Tooltip>
            </li>
          ))}
        </ul>

        <div className={`mt-auto border-t border-outline-variant py-3 ${navCollapsed ? 'px-0' : 'p-3'}`}>
          <Tooltip
            label={navCollapsed ? waltenName : ''}
            placement="right"
            className={navCollapsed ? 'w-full' : ''}
          >
            <NavLink
              to="/walten"
              aria-label={navCollapsed ? waltenName : undefined}
              className={navLinkClass(navCollapsed)}
            >
              <AgentIcon name={waltenIcon} />
              {navCollapsed ? null : <span className="flex-1 truncate">{waltenName}</span>}
            </NavLink>
          </Tooltip>
        </div>

        {offline ? (
          <div
            className={`space-y-2 border-t border-error/50 bg-error/10 py-4 font-mono text-data text-error ${
              navCollapsed ? 'px-0 text-center' : 'px-5'
            }`}
          >
            <Tooltip label={navCollapsed ? `API offline — ${offline}` : ''} placement="right">
              <span className="flex items-center justify-center gap-2">
                <OfflineIcon />
                {navCollapsed ? null : 'API offline'}
              </span>
            </Tooltip>
            {navCollapsed ? null : <p className="leading-relaxed">{offline}</p>}
          </div>
        ) : navCollapsed ? (
          // Collapsed, the schedule detail has nowhere to go; the running dot
          // is the one piece worth keeping, with the rest on hover.
          <Tooltip
            label={`${status?.running ? 'Scraping…' : 'Idle'} · last ${relativeTime(status?.last_run)}`}
            placement="right"
          >
            <span className="flex w-full justify-center border-t border-outline-variant py-4">
              <span
                className={`inline-block h-2 w-2 rounded-full ${status?.running ? 'bg-tertiary' : 'bg-primary'}`}
              />
            </span>
          </Tooltip>
        ) : (
          <div className="space-y-1 overflow-hidden border-t border-outline-variant px-5 py-4 font-mono text-data text-on-surface-variant">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${status?.running ? 'bg-tertiary' : 'bg-primary'}`}
                aria-hidden="true"
              />
              {status?.running ? 'Scraping…' : 'Idle'}
            </div>
            <div className="truncate" title={status?.last_run || ''}>
              Last: {relativeTime(status?.last_run)}
            </div>
            <div className="truncate" title={status?.next_run || ''}>
              Next: {formatDateTime(status?.next_run)}
            </div>
            {stats ? <div className="text-primary">{stats.strong_matches} strong matches</div> : null}
          </div>
        )}

        <button
          type="button"
          onClick={toggleNav}
          aria-expanded={!navCollapsed}
          aria-label={navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={navCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="flex cursor-pointer items-center justify-center gap-2 border-t border-outline-variant py-2 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
        >
          <ChevronIcon className={`h-4 w-4 transition-transform ${navCollapsed ? '' : 'rotate-180'}`} />
          {navCollapsed ? null : <span className="font-mono text-data">Collapse</span>}
        </button>
      </nav>

      <ResizeHandle
        orientation="vertical"
        label="Resize the sidebar"
        value={navWidth}
        onChange={setNavWidth}
        onReset={() => setNavWidth(NAV_WIDTH.default)}
        min={NAV_WIDTH.min}
        max={NAV_WIDTH.max}
      />

      <main className="min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/opportunities" replace />} />
          <Route path="/opportunities" element={<Opportunities onMutate={refreshHeader} />} />
          <Route path="/applications" element={<Applications onMutate={refreshHeader} />} />
          <Route path="/resumes" element={<Resumes onMutate={refreshHeader} />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/sources" element={<Sources onMutate={refreshHeader} />} />
          <Route path="/settings" element={<Settings onMutate={refreshHeader} />} />
          <Route path="/settings/:section" element={<SettingsSection onMutate={refreshHeader} />} />
          <Route path="/walten" element={<Walten />} />
          <Route
            path="*"
            element={
              <div className="overflow-auto p-10">
                <h1>Not found</h1>
                <p className="mt-2 text-on-surface-variant">That route does not exist.</p>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  )
}
