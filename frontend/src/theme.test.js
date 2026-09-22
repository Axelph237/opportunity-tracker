import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_THEME,
  VARIANTS,
  applyRoles,
  applyTheme,
  buildRoles,
  hueSwatches,
  isValidHex,
  normalizeHex,
  readThemeConfig,
  readableOn,
  resolveMode,
  writeThemeConfig,
} from './theme'

// The exact MD3 role set theme.js promises to generate and write to the
// document (mirrors the `ROLES` list at theme.js:82-95 — not exported, so this
// is the contract copied into the test rather than re-derived from it).
const EXPECTED_ROLES = [
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

const HEX_RE = /^#[0-9a-fA-F]{6}$/

describe('isValidHex / normalizeHex', () => {
  it('accepts 3- and 6-digit hex, with or without a leading #', () => {
    expect(isValidHex('#fff')).toBe(true)
    expect(isValidHex('fff')).toBe(true)
    expect(isValidHex('#00c2ff')).toBe(true)
    expect(isValidHex('00C2FF')).toBe(true)
  })

  it('rejects garbage', () => {
    expect(isValidHex('')).toBe(false)
    expect(isValidHex('not-a-color')).toBe(false)
    expect(isValidHex('#12345')).toBe(false)
  })

  it('normalizes to an uppercase 6-digit #RRGGBB', () => {
    expect(normalizeHex('#fff')).toBe('#FFFFFF')
    expect(normalizeHex('abc')).toBe('#AABBCC')
    expect(normalizeHex('#00c2ff')).toBe('#00C2FF')
  })
})

describe('resolveMode', () => {
  it('resolves "light" and "dark" directly', () => {
    expect(resolveMode('light')).toBe('light')
    expect(resolveMode('dark')).toBe('dark')
  })

  it('falls back to dark for an unrecognized mode', () => {
    expect(resolveMode('sepia')).toBe('dark')
  })

  it('falls back to dark for "system" when the environment cannot report a preference', () => {
    // jsdom does not implement matchMedia; theme.js guards with `?.` for
    // exactly this environment and should not throw.
    expect(() => resolveMode('system')).not.toThrow()
    expect(resolveMode('system')).toBe('dark')
  })
})

describe('buildRoles', () => {
  it('produces every expected MD3 token for the default config', () => {
    const roles = buildRoles(DEFAULT_THEME, 'dark')
    for (const role of EXPECTED_ROLES) {
      expect(roles).toHaveProperty(role)
      expect(roles[role]).toMatch(HEX_RE)
    }
    expect(Object.keys(roles).sort()).toEqual([...EXPECTED_ROLES].sort())
  })

  it('produces the full token set for every declared variant', () => {
    for (const variant of VARIANTS) {
      const roles = buildRoles({ ...DEFAULT_THEME, variant: variant.value }, 'dark')
      expect(Object.keys(roles).sort()).toEqual([...EXPECTED_ROLES].sort())
      expect(roles.primary).toMatch(HEX_RE)
    }
  })

  it('produces different colours for light vs dark mode from the same source', () => {
    const dark = buildRoles(DEFAULT_THEME, 'dark')
    const light = buildRoles(DEFAULT_THEME, 'light')
    expect(dark.background).not.toBe(light.background)
    expect(dark.onSurface).not.toBe(light.onSurface)
    expect(dark.surface).not.toBe(light.surface)
  })

  it('falls back to the default source colour for an invalid hex', () => {
    const invalid = buildRoles({ ...DEFAULT_THEME, source: 'not-a-color' }, 'dark')
    const fallback = buildRoles({ ...DEFAULT_THEME, source: DEFAULT_THEME.source }, 'dark')
    expect(invalid.primary).toBe(fallback.primary)
  })

  it('produces a different palette for a different source colour', () => {
    const cyan = buildRoles({ ...DEFAULT_THEME, source: '#00C2FF' }, 'dark')
    const magenta = buildRoles({ ...DEFAULT_THEME, source: '#C2569E' }, 'dark')
    expect(cyan.primary).not.toBe(magenta.primary)
  })
})

describe('applyRoles', () => {
  it('writes each role as a kebab-case CSS custom property', () => {
    const target = document.createElement('div')
    applyRoles({ onSurfaceVariant: '#112233', primary: '#445566' }, target)
    expect(target.style.getPropertyValue('--md-sys-color-on-surface-variant')).toBe('#112233')
    expect(target.style.getPropertyValue('--md-sys-color-primary')).toBe('#445566')
  })
})

describe('readThemeConfig / writeThemeConfig', () => {
  it('returns the default theme when nothing is stored', () => {
    expect(readThemeConfig()).toEqual(DEFAULT_THEME)
  })

  it('returns defaults merged with corrupt storage rather than throwing', () => {
    localStorage.setItem('opportunity-tracker.theme', '{not json')
    expect(() => readThemeConfig()).not.toThrow()
    expect(readThemeConfig()).toEqual(DEFAULT_THEME)
  })

  it('persists and reloads a config, merged over the defaults', () => {
    writeThemeConfig({ source: '#C2569E' })
    expect(readThemeConfig()).toEqual({ ...DEFAULT_THEME, source: '#C2569E' })
  })

  it('dispatches a theme-changed event so listeners can react live', () => {
    const handler = vi.fn()
    window.addEventListener('theme-changed', handler)
    writeThemeConfig({ source: '#3FAE6B' })
    expect(handler).toHaveBeenCalledTimes(1)
    window.removeEventListener('theme-changed', handler)
  })
})

describe('applyTheme', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('style')
    delete document.documentElement.dataset.mode
  })

  it('writes CSS variables onto the document root and records the resolved mode', () => {
    applyTheme({ ...DEFAULT_THEME, mode: 'light' })
    expect(document.documentElement.style.getPropertyValue('--md-sys-color-primary')).toMatch(HEX_RE)
    expect(document.documentElement.dataset.mode).toBe('light')
    expect(document.documentElement.style.colorScheme).toBe('light')
  })
})

describe('hueSwatches', () => {
  it('generates the requested number of valid, distinct hex colours', () => {
    const swatches = hueSwatches('#00C2FF', 12)
    expect(swatches).toHaveLength(12)
    swatches.forEach((hex) => expect(hex).toMatch(HEX_RE))
    expect(new Set(swatches).size).toBe(12)
  })

  it('defaults to 12 swatches', () => {
    expect(hueSwatches('#00C2FF')).toHaveLength(12)
  })
})

describe('readableOn', () => {
  it('picks black text on light backgrounds and white text on dark backgrounds', () => {
    expect(readableOn('#FFFFFF')).toBe('#000000')
    expect(readableOn('#000000')).toBe('#FFFFFF')
  })

  it('falls back to black for an invalid colour', () => {
    expect(readableOn('nope')).toBe('#000000')
  })
})
