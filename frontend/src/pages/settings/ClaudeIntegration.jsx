import { api } from '../../api'

export default function ClaudeIntegration({ settings, act }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-6 rounded border border-outline-variant bg-surface-container p-4">
        <div>
          <div className="label-data">claude CLI</div>
          <div className={`mt-1 font-mono ${settings?.claude_cli ? 'text-primary' : 'text-error'}`}>
            {settings?.claude_cli ? 'available' : 'not found on PATH'}
          </div>
        </div>
        <label className="space-y-1">
          <span className="label-data block">Model</span>
          <input
            key={settings?.settings?.model}
            className="field w-40 font-mono"
            defaultValue={settings?.settings?.model || 'sonnet'}
            onBlur={(event) => {
              const value = event.target.value.trim()
              if (value && value !== settings?.settings?.model) {
                act(() => api.updateSettings({ model: value }), `Model set to ${value}.`)
              }
            }}
          />
        </label>
        <div className="min-w-0">
          <div className="label-data">Database</div>
          <div className="mt-1 truncate font-mono text-on-surface-variant">{settings?.database}</div>
        </div>
      </div>

      <p className="text-on-surface-variant">
        Classification, discovery and resume advice all shell out to the local CLI in headless mode
        (<span className="font-mono text-on-surface">claude -p</span>), using your existing login. No{' '}
        <span className="font-mono text-on-surface">ANTHROPIC_API_KEY</span> is read by this app.
      </p>
      <p className="text-on-surface-variant">
        If the CLI shows as not found, set <span className="font-mono text-on-surface">CLAUDE_BIN</span>{' '}
        in <span className="font-mono text-on-surface">.env</span> to its full path.
      </p>
    </div>
  )
}
