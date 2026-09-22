import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import Dropdown from './Dropdown'
import { AGENT_ICON_NAMES, AgentIcon, CheckIcon } from './icons'
import {
  CONTRAST_LEVELS,
  DEFAULT_THEME,
  SWATCHES,
  VARIANTS,
  applyTheme,
  buildRoles,
  hueSwatches,
  isValidHex,
  normalizeHex,
  readThemeConfig,
  readableOn,
  writeThemeConfig,
} from '../theme'

const MODES = [
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
  { value: 'system', label: 'System' },
]

// The roles worth showing: what each one actually paints in this app.
const PREVIEW_ROLES = [
  ['surface', 'onSurface', 'Page background'],
  ['surfaceContainer', 'onSurface', 'Cards and panels'],
  ['surfaceContainerHigh', 'onSurface', 'Rows on hover, buttons'],
  ['primary', 'onPrimary', 'Accents, links, strong matches'],
  ['primaryContainer', 'onPrimaryContainer', 'Primary buttons'],
  ['tertiary', 'onTertiary', 'Warnings, deadlines'],
  ['error', 'onError', 'Destructive actions'],
  ['outlineVariant', 'onSurfaceVariant', 'Borders and dividers'],
]

function Segmented({ value, onChange, options, label }) {
  return (
    <div className="inline-flex rounded border border-outline-variant" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`px-3 py-1.5 transition-colors first:rounded-l last:rounded-r ${
            value === option.value
              ? 'bg-primary-container text-on-primary-container'
              : 'text-on-surface-variant hover:text-on-surface'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

function Swatch({ hex, name, selected, onClick }) {
  return (
    <button
      type="button"
      title={`${name} · ${hex}`}
      aria-label={`${name} ${hex}`}
      aria-pressed={selected}
      onClick={onClick}
      style={{ backgroundColor: hex }}
      className={`flex h-9 w-9 items-center justify-center rounded-full border-2 transition-transform hover:scale-110 ${
        selected ? 'border-on-surface' : 'border-transparent'
      }`}
    >
      {selected ? <CheckIcon className="h-4 w-4" style={{ color: readableOn(hex) }} /> : null}
    </button>
  )
}

/**
 * Theme builder. A source colour plus an MD3 scheme variant is all Material
 * needs; the library derives every surface, accent and `on-` colour from it, so
 * the user picks one colour and the whole app stays legible.
 */
export default function ThemeSettings({ settings, act, hideAgent = false }) {
  const [config, setConfig] = useState(readThemeConfig)
  const [hexDraft, setHexDraft] = useState(() => readThemeConfig().source)

  // Applying on every change is what makes the page itself the live preview.
  useEffect(() => {
    applyTheme(config)
    writeThemeConfig(config)
  }, [config])

  const set = (patch) => setConfig((current) => ({ ...current, ...patch }))

  const hues = useMemo(() => hueSwatches(config.source), [config.source])
  const preview = useMemo(() => buildRoles(config), [config])

  const commitHex = (raw) => {
    setHexDraft(raw)
    if (isValidHex(raw)) set({ source: normalizeHex(raw) })
  }

  const pick = (hex) => {
    setHexDraft(hex)
    set({ source: hex })
  }

  const isDefault =
    config.source === DEFAULT_THEME.source &&
    config.variant === DEFAULT_THEME.variant &&
    config.mode === DEFAULT_THEME.mode &&
    Number(config.contrast) === DEFAULT_THEME.contrast

  const agentName = settings?.settings?.walten_name ?? 'Walten'
  const agentIcon = settings?.settings?.walten_icon ?? 'Dog'

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <span className="label-data">Appearance</span>
        <Segmented value={config.mode} onChange={(mode) => set({ mode })} options={MODES} label="Appearance" />
        <span className="text-on-surface-variant">
          {config.mode === 'system' ? 'Follows your operating system setting.' : null}
        </span>
      </div>

      <div className="space-y-3">
        <span className="label-data block">Source colour</span>
        <div className="flex flex-wrap gap-2">
          {SWATCHES.map((swatch) => (
            <Swatch
              key={swatch.hex}
              {...swatch}
              selected={config.source.toUpperCase() === swatch.hex.toUpperCase()}
              onClick={() => pick(swatch.hex)}
            />
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          {hues.map((hex) => (
            <Swatch
              key={hex}
              hex={hex}
              name="Hue"
              selected={config.source.toUpperCase() === hex.toUpperCase()}
              onClick={() => pick(hex)}
            />
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2">
            <span className="label-data">Hex</span>
            <input
              className={`field w-32 font-mono uppercase ${isValidHex(hexDraft) ? '' : 'border-error'}`}
              value={hexDraft}
              onChange={(event) => commitHex(event.target.value)}
              placeholder="#00C2FF"
              spellCheck="false"
            />
          </label>
          <span
            className="h-9 w-9 shrink-0 rounded-full border border-outline-variant"
            style={{ backgroundColor: isValidHex(hexDraft) ? normalizeHex(hexDraft) : 'transparent' }}
            aria-hidden="true"
          />
          {!isValidHex(hexDraft) ? (
            <span className="text-error">Enter a 3 or 6 digit hex colour.</span>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <label className="space-y-1">
          <span className="label-data block">Palette style</span>
          <Dropdown
            className="w-56"
            value={config.variant}
            onChange={(variant) => set({ variant: variant || DEFAULT_THEME.variant })}
            options={VARIANTS.map((v) => ({ value: v.value, label: v.label }))}
          />
        </label>
        <label className="space-y-1">
          <span className="label-data block">Contrast</span>
          <Dropdown
            className="w-40"
            value={String(config.contrast)}
            onChange={(contrast) => set({ contrast: Number(contrast ?? 0) })}
            options={CONTRAST_LEVELS.map((c) => ({ value: String(c.value), label: c.label }))}
          />
        </label>
        <p className="min-w-0 flex-1 text-on-surface-variant">
          {VARIANTS.find((v) => v.value === config.variant)?.hint}
        </p>
        <button
          type="button"
          className="btn"
          disabled={isDefault}
          onClick={() => {
            setConfig({ ...DEFAULT_THEME })
            setHexDraft(DEFAULT_THEME.source)
          }}
        >
          Reset
        </button>
      </div>

      <div className="space-y-2">
        <span className="label-data block">Generated tokens</span>
        <div className="grid gap-2 sm:grid-cols-2">
          {PREVIEW_ROLES.map(([role, onRole, description]) => (
            <div
              key={role}
              className="flex items-center justify-between gap-3 rounded border border-outline-variant px-3 py-2"
              style={{ backgroundColor: preview[role], color: preview[onRole] }}
            >
              <span className="min-w-0">
                <span className="block truncate">{description}</span>
                <span className="block font-mono text-data opacity-80">{role}</span>
              </span>
              <span className="shrink-0 font-mono text-data opacity-80">{preview[role]}</span>
            </div>
          ))}
        </div>
        <p className="text-on-surface-variant">
          Material derives all {Object.keys(preview).length} role tokens from your colour, so text
          stays readable on every surface.
        </p>
      </div>

      {hideAgent ? null : (
      <div className="space-y-2">
        <span className="label-data block">Agent</span>
        <div className="flex flex-wrap items-center gap-3">
          <input
            key={agentName}
            className="field w-56"
            aria-label="Agent name"
            defaultValue={agentName}
            placeholder="Walten"
            onBlur={(event) => {
              const value = event.target.value.trim() || 'Walten'
              if (value !== agentName) act?.(() => api.updateSettings({ walten_name: value }), `Agent renamed to ${value}.`)
            }}
          />
          <div className="flex flex-wrap gap-1">
            {AGENT_ICON_NAMES.map((icon) => (
              <button
                key={icon}
                type="button"
                title={icon}
                aria-label={icon}
                aria-pressed={icon === agentIcon}
                onClick={() =>
                  icon !== agentIcon && act?.(() => api.updateSettings({ walten_icon: icon }), `Icon set to ${icon}.`)
                }
                className={`rounded border p-1.5 transition-colors ${
                  icon === agentIcon
                    ? 'border-primary bg-secondary-container text-on-secondary-container'
                    : 'border-transparent text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
                }`}
              >
                <AgentIcon name={icon} />
              </button>
            ))}
          </div>
        </div>
        <span className="block font-mono text-data text-on-surface-variant">
          Name and icon of the agent tab at the bottom of the sidebar.
        </span>
      </div>
      )}
    </div>
  )
}
