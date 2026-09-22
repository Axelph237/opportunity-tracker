import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Sources from './Sources'
import { ConfirmProvider } from '../components/ConfirmDialog'
import { api } from '../api'

// Sources.jsx talks to the real backend through the `api` module; mock every
// method it calls so this test never touches the network (and never risks
// the real ../data/opportunities.db).
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    api: {
      ...actual.api,
      sources: vi.fn(),
      proposals: vi.fn(),
      scrapeStatus: vi.fn(),
      scrapeSource: vi.fn(),
      updateSource: vi.fn(),
      deleteSource: vi.fn(),
      createSource: vi.fn(),
      discoverSources: vi.fn(),
    },
  }
})

const STATUS = { running: false, last_run: '2026-09-22 10:00:00', next_run: '2026-09-22 16:00:00' }

function baseSource(overrides) {
  return {
    id: 1,
    name: 'Example Co',
    url: 'https://example.com/careers',
    type: 'company_careers',
    active: true,
    last_result_count: 3,
    date_added: '2026-09-01',
    added_by: 'user',
    last_scraped: null,
    last_status: null,
    last_error: null,
    ...overrides,
  }
}

function renderSources(sources) {
  api.sources.mockResolvedValue(sources)
  api.proposals.mockResolvedValue([])
  api.scrapeStatus.mockResolvedValue(STATUS)
  return render(
    <ConfirmProvider>
      <Sources onMutate={() => {}} />
    </ConfirmProvider>,
  )
}

describe('Sources / LastScraped + Scrape button', () => {
  // relativeTime() parses SQLite-shaped "YYYY-MM-DD HH:MM:SS" timestamps (what
  // `last_scraped` is) as *local* time rather than UTC (see the documented bug
  // in format.test.js). Pin TZ to UTC here so that quirk is a no-op and this
  // test is only exercising Sources.jsx, not format.js's timezone handling.
  let originalTZ
  beforeAll(() => {
    originalTZ = process.env.TZ
    process.env.TZ = 'UTC'
  })
  afterAll(() => {
    process.env.TZ = originalTZ
  })

  beforeEach(() => {
    vi.setSystemTime(new Date('2026-09-22T16:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('a blocked source shows a "Blocked" tag and an aria-disabled Scrape button that never calls the scrape API', async () => {
    const user = userEvent.setup()
    const source = baseSource({
      name: 'Blocked Co',
      last_status: 'blocked',
      last_error: '403 Forbidden',
      last_scraped: '2026-09-22 14:00:00',
    })
    renderSources([source])

    expect(await screen.findByText('Blocked')).toBeInTheDocument()
    const row = screen.getByText('Blocked Co').closest('tr')
    const scrapeButton = within(row).getByRole('button', { name: /Scrape/ })
    expect(scrapeButton).toHaveAttribute('aria-disabled', 'true')

    await user.click(scrapeButton)
    expect(api.scrapeSource).not.toHaveBeenCalled()
  })

  it('a source with a "error" last_status shows "Failed" with an ENABLED Scrape button that calls the API', async () => {
    const user = userEvent.setup()
    const source = baseSource({
      id: 42,
      name: 'Flaky Co',
      last_status: 'error',
      last_error: 'Timed out',
      last_scraped: '2026-09-22 14:00:00',
    })
    api.scrapeSource.mockResolvedValue(undefined)
    renderSources([source])

    expect(await screen.findByText('Failed')).toBeInTheDocument()
    const row = screen.getByText('Flaky Co').closest('tr')
    const scrapeButton = within(row).getByRole('button', { name: /Scrape/ })
    expect(scrapeButton).not.toHaveAttribute('aria-disabled')
    expect(scrapeButton).toBeEnabled()

    await user.click(scrapeButton)
    await waitFor(() => expect(api.scrapeSource).toHaveBeenCalledWith(42))
  })

  it('a source with no last_status shows the relative last-scraped time instead of a status tag', async () => {
    const source = baseSource({
      name: 'Quiet Co',
      last_status: null,
      last_scraped: '2026-09-22 15:00:00', // 1 hour before the pinned "now"
    })
    renderSources([source])

    const row = (await screen.findByText('Quiet Co')).closest('tr')
    expect(within(row).getByText('1 hour ago')).toBeInTheDocument()
    expect(within(row).queryByText('Blocked')).not.toBeInTheDocument()
    expect(within(row).queryByText('Failed')).not.toBeInTheDocument()
  })

  it('a source that has never been scraped shows "never"', async () => {
    const source = baseSource({ name: 'New Co', last_status: null, last_scraped: null })
    renderSources([source])
    const row = (await screen.findByText('New Co')).closest('tr')
    expect(within(row).getByText('never')).toBeInTheDocument()
  })
})
