import { api } from '../../api'

const FIELDS = [
  ['max_chunks_per_source', 'Max listings per source'],
  ['request_timeout_seconds', 'HTTP timeout (s)'],
  ['domain_delay_seconds', 'Delay per domain (s)'],
]

export default function ScrapeTuning({ settings, act }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        {FIELDS.map(([key, label]) => (
          <label key={key} className="space-y-1">
            <span className="label-data block">{label}</span>
            <input
              key={settings?.settings?.[key]}
              type="number"
              min="1"
              className="field font-mono"
              defaultValue={settings?.settings?.[key] || ''}
              onBlur={(event) => {
                const value = Number(event.target.value)
                if (value && String(value) !== settings?.settings?.[key]) {
                  act(() => api.updateSettings({ [key]: value }), `${label} updated.`)
                }
              }}
            />
          </label>
        ))}
      </div>

      <label className="flex items-start gap-3 rounded border border-outline-variant bg-surface-container p-4">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 accent-primary"
          checked={settings?.settings?.verify_listing_urls !== '0'}
          onChange={(event) =>
            act(
              () => api.updateSettings({ verify_listing_urls: event.target.checked }),
              event.target.checked ? 'Listing URLs will be verified.' : 'Listing verification disabled.',
            )
          }
        />
        <span>
          <span className="text-on-surface">Verify every listing URL before saving it</span>
          <span className="mt-1 block text-on-surface-variant">
            Fetches each candidate and discards anything that 404s, redirects to a site root or reads
            as an error page. Costs one request per candidate, and saves the Claude call that would
            have classified it.
          </span>
        </span>
      </label>
    </div>
  )
}
