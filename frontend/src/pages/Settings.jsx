import { useNavigate } from 'react-router-dom'
import PageLayout from '../components/PageLayout'
import { useSuppressedConfirms } from '../components/ConfirmDialog'
import { ChevronIcon, SettingsIcon } from '../components/icons'
import { SECTIONS } from './settings/registry'
import { useSettings } from './settings/useSettings'
import { readThemeConfig } from '../theme'

/**
 * Settings index: one row per section, each opening its own page. Rows show the
 * current value so the state of a section is readable without opening it.
 */
export default function Settings({ onMutate }) {
  const navigate = useNavigate()
  const { settings, resume, status, error } = useSettings(onMutate)
  const suppressed = useSuppressedConfirms()
  const context = { settings, resume, status, suppressed, theme: readThemeConfig() }

  return (
    <PageLayout
      title="Settings"
      icon="settings"
      description="How the tracker looks and runs."
      error={error}
    >
      <div className="max-w-3xl py-6">
        <ul className="divide-y divide-outline-variant rounded border border-outline-variant bg-surface-container">
          {SECTIONS.map((section) => (
            <li key={section.slug}>
              <button
                type="button"
                onClick={() => navigate(`/settings/${section.slug}`)}
                className="flex w-full items-center gap-4 px-4 py-4 text-left transition-colors hover:bg-surface-container-high"
              >
                <span className="text-on-surface-variant">
                  <SettingsIcon name={section.slug} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-on-surface">{section.title}</span>
                  <span className="block text-on-surface-variant">{section.description}</span>
                </span>
                <span className="shrink-0 truncate font-mono text-data text-on-surface-variant">
                  {section.summary(context)}
                </span>
                <span className="shrink-0 text-on-surface-variant">
                  <ChevronIcon />
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </PageLayout>
  )
}
