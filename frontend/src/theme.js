/**
 * Theme engine.
 *
 * Every colour in the app comes from a Material Design 3 palette generated at
 * runtime from a single source colour, using Google's own
 * `@material/material-color-utilities`. The generator produces tonal palettes in
 * the HCT colour space and derives the full MD3 role set from them, so contrast
 * between a surface and its `on-` colour holds for any source colour the user
 * picks — which hand-mixing hex values cannot guarantee.
 *
 * Roles are written to `:root` as `--md-sys-color-<role>` and Tailwind's colour
 * utilities are mapped onto those variables in `index.css`, so changing the
 * source colour restyles every component without re-rendering anything.
 */
import {
  Hct,
  MaterialDynamicColors,
  SchemeContent,
  SchemeExpressive,
  SchemeFidelity,
  SchemeMonochrome,
  SchemeNeutral,
  SchemeRainbow,
  SchemeTonalSpot,
  SchemeVibrant,
  argbFromHex,
  hexFromArgb,
} from '@material/material-color-utilities'

const STORAGE_KEY = 'opportunity-tracker.theme'

export const DEFAULT_THEME = {
  source: '#00C2FF', // the instrument cyan the app shipped with
  variant: 'vibrant', // keeps the source colour saturated, closest to the original instrument palette
  mode: 'dark',
  contrast: 0,
}

/** MD3 scheme variants — how far the palette strays from the source colour. */
export const VARIANTS = [
  { value: 'tonalSpot', label: 'Tonal spot', hint: 'Material default — muted, balanced' },
  { value: 'vibrant', label: 'Vibrant', hint: 'Keeps the source colour saturated' },
  { value: 'expressive', label: 'Expressive', hint: 'Shifts hue for a livelier palette' },
  { value: 'fidelity', label: 'Fidelity', hint: 'Stays closest to the exact colour' },
  { value: 'content', label: 'Content', hint: 'Tuned for imagery and content' },
  { value: 'neutral', label: 'Neutral', hint: 'Nearly greyscale, colour only in accents' },
  { value: 'monochrome', label: 'Monochrome', hint: 'Greyscale' },
  { value: 'rainbow', label: 'Rainbow', hint: 'Wide spread across hues' },
]

const SCHEMES = {
  tonalSpot: SchemeTonalSpot,
  vibrant: SchemeVibrant,
  expressive: SchemeExpressive,
  fidelity: SchemeFidelity,
  content: SchemeContent,
  neutral: SchemeNeutral,
  monochrome: SchemeMonochrome,
  rainbow: SchemeRainbow,
}

export const CONTRAST_LEVELS = [
  { value: 0, label: 'Standard' },
  { value: 0.5, label: 'Medium' },
  { value: 1, label: 'High' },
]

/** Ready-made source colours, so a theme is one click away. */
export const SWATCHES = [
  { hex: '#00C2FF', name: 'Instrument cyan' },
  { hex: '#4F7CFF', name: 'Cobalt' },
  { hex: '#7C5CFF', name: 'Violet' },
  { hex: '#C2569E', name: 'Magenta' },
  { hex: '#E05263', name: 'Coral' },
  { hex: '#F0A500', name: 'Amber' },
  { hex: '#3FAE6B', name: 'Emerald' },
  { hex: '#00A4A6', name: 'Teal' },
  { hex: '#8A8F98', name: 'Graphite' },
]

// Every MD3 role that gets written to the document.
const ROLES = [
  'background', 'onBackground',
  'surface', 'surfaceDim', 'surfaceBright',
  'surfaceContainerLowest', 'surfaceContainerLow', 'surfaceContainer',
  'surfaceContainerHigh', 'surfaceContainerHighest',
  'onSurface', 'surfaceVariant', 'onSurfaceVariant',
  'outline', 'outlineVariant',
  'inverseSurface', 'inverseOnSurface', 'inversePrimary',
  'shadow', 'scrim', 'surfaceTint',
  'primary', 'onPrimary', 'primaryContainer', 'onPrimaryContainer',
  'secondary', 'onSecondary', 'secondaryContainer', 'onSecondaryContainer',
  'tertiary', 'onTertiary', 'tertiaryContainer', 'onTertiaryContainer',
  'error', 'onError', 'errorContainer', 'onErrorContainer',
]


const kebab = (role) => role.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)

export function isValidHex(value) {
  return /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(value || '').trim())
}

export function normalizeHex(value) {
  let hex = String(value || '').trim().replace(/^#/, '')
  if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('')
  return `#${hex.toUpperCase()}`
}

/** Resolve 'system' against the OS preference. */
export function resolveMode(mode) {
  if (mode !== 'system') return mode === 'light' ? 'light' : 'dark'
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

/** Build the full MD3 role map for a config. Returns `{ role: '#rrggbb' }`. */
export function buildRoles(config = DEFAULT_THEME, modeOverride) {
  const merged = { ...DEFAULT_THEME, ...config }
  const Scheme = SCHEMES[merged.variant] || SchemeTonalSpot
  const dark = (modeOverride || resolveMode(merged.mode)) === 'dark'
  const source = isValidHex(merged.source) ? normalizeHex(merged.source) : DEFAULT_THEME.source
  const scheme = new Scheme(Hct.fromInt(argbFromHex(source)), dark, Number(merged.contrast) || 0)

  const roles = {}
  for (const role of ROLES) {
    const dynamicColor = MaterialDynamicColors[role]
    if (dynamicColor) roles[role] = hexFromArgb(dynamicColor.getArgb(scheme))
  }

  return roles
}

/** Write a role map onto an element (the document root by default). */
export function applyRoles(roles, target = document.documentElement) {
  for (const [role, hex] of Object.entries(roles)) {
    target.style.setProperty(`--md-sys-color-${kebab(role)}`, hex)
  }
}

export function readThemeConfig() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    return stored && typeof stored === 'object' ? { ...DEFAULT_THEME, ...stored } : { ...DEFAULT_THEME }
  } catch {
    return { ...DEFAULT_THEME }
  }
}

export function writeThemeConfig(config) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    /* private mode: the theme applies for this session only */
  }
  window.dispatchEvent(new CustomEvent('theme-changed', { detail: config }))
}

/** Generate, apply and persist. Returns the config that was applied. */
export function applyTheme(config) {
  const merged = { ...DEFAULT_THEME, ...config }
  const mode = resolveMode(merged.mode)
  applyRoles(buildRoles(merged, mode))
  // Tells the browser which way to render native UI: scrollbars, form controls,
  // the date picker popup, and the canvas behind the page.
  document.documentElement.style.colorScheme = mode
  document.documentElement.dataset.mode = mode
  return merged
}

/**
 * A row of swatches at the same chroma and tone as the current source colour,
 * spread evenly around the hue circle. Generated in HCT so every swatch is
 * perceptually as vivid as the others, which evenly spaced RGB values are not.
 */
export function hueSwatches(source, count = 12) {
  const base = Hct.fromInt(argbFromHex(isValidHex(source) ? normalizeHex(source) : DEFAULT_THEME.source))
  const chroma = Math.max(base.chroma, 48)
  const tone = Math.min(Math.max(base.tone, 45), 70)
  return Array.from({ length: count }, (_, index) =>
    hexFromArgb(Hct.from((index * (360 / count)) % 360, chroma, tone).toInt()),
  )
}

/** Black or white, whichever is readable on the given colour. */
export function readableOn(hex) {
  if (!isValidHex(hex)) return '#000000'
  return Hct.fromInt(argbFromHex(normalizeHex(hex))).tone > 60 ? '#000000' : '#FFFFFF'
}

let systemWatcher = null

/**
 * Apply the stored theme and keep it in step with the OS when mode is 'system'.
 * Called once before the app renders.
 */
export function initTheme() {
  const config = applyTheme(readThemeConfig())
  const media = window.matchMedia?.('(prefers-color-scheme: light)')
  if (media && !systemWatcher) {
    systemWatcher = () => {
      const current = readThemeConfig()
      if (current.mode === 'system') applyTheme(current)
    }
    media.addEventListener('change', systemWatcher)
  }
  return config
}
