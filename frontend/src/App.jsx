import { useCallback, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import Applications from './pages/Applications'
import Insights from './pages/Insights'
import Onboarding from './pages/Onboarding'
import Opportunities from './pages/Opportunities'
import Settings from './pages/Settings'
import SettingsSection from './pages/settings/SettingsSection'
import Sources from './pages/Sources'
import Walten from './pages/Walten'
import { AgentIcon, NavIcon, OfflineIcon } from './components/icons'
import { ApiOfflineError, api } from './api'
import { formatDateTime, relativeTime } from './format'

const NAV = [
  { to: '/opportunities', label: 'Opportunities', icon: 'opportunities', badge: 'opportunities' },
  { to: '/applications', label: 'Applications', icon: 'applications', badge: 'applications' },
  { to: '/insights', label: 'Role analysis', icon: 'insights' },
  { to: '/sources', label: 'Sources', icon: 'sources', badge: 'pending_proposals' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]

const navLinkClass = ({ isActive }) =>
  `flex items-center gap-3 rounded px-3 py-2 transition-colors ${
    isActive
      ? 'border-l-2 border-primary bg-secondary-container pl-[10px] text-on-secondary-container'
      : 'border-l-2 border-transparent pl-[10px] text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
  }`

export default function App() {
  const [stats, setStats] = useState(null)
  const [status, setStatus] = useState(null)
  const [offline, setOffline] = useState(null)
  const [waltenName, setWaltenName] = useState('Walten')
  const [waltenIcon, setWaltenIcon] = useState('Dog')
  // null until the first stats call answers; avoids flashing the app then the wizard.
  const [onboarded, setOnboarded] = useState(null)

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
      <nav className="flex h-full w-52 shrink-0 flex-col border-r border-outline-variant bg-surface-container">
        <div className="border-b border-outline-variant px-5 py-5">
          <div className="font-mono text-data tracking-[0.2em] text-primary">OPPORTUNITY</div>
          <div className="font-mono text-data tracking-[0.2em] text-on-surface-variant">TRACKER</div>
        </div>

        <ul className="space-y-1 p-3">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={navLinkClass}
              >
                <NavIcon name={item.icon} />
                <span className="flex-1">{item.label}</span>
                {item.badge && stats?.[item.badge] ? (
                  <span className="font-mono text-data opacity-80">{stats[item.badge]}</span>
                ) : null}
              </NavLink>
            </li>
          ))}
        </ul>

        <div className="mt-auto border-t border-outline-variant p-3">
          <NavLink to="/walten" className={navLinkClass}>
            <AgentIcon name={waltenIcon} />
            <span className="flex-1 truncate">{waltenName}</span>
          </NavLink>
        </div>

        {offline ? (
          <div className="space-y-2 border-t border-error/50 bg-error/10 px-5 py-4 font-mono text-data text-error">
            <div className="flex items-center gap-2">
              <OfflineIcon />
              API offline
            </div>
            <p className="leading-relaxed">{offline}</p>
          </div>
        ) : (
          <div className="space-y-1 border-t border-outline-variant px-5 py-4 font-mono text-data text-on-surface-variant">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${status?.running ? 'bg-tertiary' : 'bg-primary'}`}
                aria-hidden="true"
              />
              {status?.running ? 'Scraping…' : 'Idle'}
            </div>
            <div title={status?.last_run || ''}>Last: {relativeTime(status?.last_run)}</div>
            <div title={status?.next_run || ''}>Next: {formatDateTime(status?.next_run)}</div>
            {stats ? <div className="text-primary">{stats.strong_matches} strong matches</div> : null}
          </div>
        )}
      </nav>

      <main className="min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/opportunities" replace />} />
          <Route path="/opportunities" element={<Opportunities onMutate={refreshHeader} />} />
          <Route path="/applications" element={<Applications onMutate={refreshHeader} />} />
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
