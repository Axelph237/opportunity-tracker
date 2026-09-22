import Appearance from './Appearance'
import ClaudeIntegration from './ClaudeIntegration'
import Confirmations from './Confirmations'
import Resume from './Resume'
import ScrapeTuning from './ScrapeTuning'
import Scraper from './Scraper'
import { titleCase } from '../../format'

/**
 * The settings sections, each its own page under /settings/<slug>.
 *
 * `summary` renders the current value on the index row so the state of a section
 * is visible without opening it.
 */
export const SECTIONS = [
  {
    slug: 'appearance',
    title: 'Appearance',
    description: 'Light or dark, and a palette built from any colour.',
    Component: Appearance,
    summary: ({ theme }) => `${titleCase(theme.mode)} · ${theme.source}`,
  },
  {
    slug: 'resume',
    title: 'Resume',
    description: 'The document every listing is scored against.',
    Component: Resume,
    summary: ({ resume }) => resume?.filename || 'none loaded',
  },
  {
    slug: 'scraper',
    title: 'Scraper',
    description: 'Schedule, and manual runs.',
    Component: Scraper,
    summary: ({ settings, status }) =>
      settings ? `${settings.cron_schedule}${status?.running ? ' · running' : ''}` : '—',
  },
  {
    slug: 'claude',
    title: 'Claude',
    description: 'Runs through your local CLI. No API key.',
    Component: ClaudeIntegration,
    summary: ({ settings }) =>
      settings ? `${settings.claude_cli ? 'available' : 'not found'} · ${settings.settings?.model}` : '—',
  },
  {
    slug: 'confirmations',
    title: 'Confirmations',
    description: 'Which actions ask before going ahead.',
    Component: Confirmations,
    summary: ({ suppressed }) =>
      suppressed.length ? `${suppressed.length} skipped` : 'all enabled',
  },
  {
    slug: 'tuning',
    title: 'Scrape tuning',
    description: 'Limits and checks applied on the next run.',
    Component: ScrapeTuning,
    summary: ({ settings }) =>
      settings ? `${settings.settings?.max_chunks_per_source} per source` : '—',
  },
]

export const findSection = (slug) => SECTIONS.find((section) => section.slug === slug)
