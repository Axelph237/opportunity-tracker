/**
 * Every icon in the app, mapped from an app concept to a Phosphor icon.
 *
 * Components import from here rather than from `@phosphor-icons/react` directly,
 * so the icon set, its weights and its sizes are decided in one file. Phosphor
 * icons inherit `currentColor`, so tone comes from the surrounding text colour.
 */
import {
  ArrowLeft,
  ArrowUUpLeft,
  ArrowUpRight,
  CaretDown,
  CaretRight,
  CaretUp,
  CaretUpDown,
  Bird,
  Bug,
  BugBeetle,
  Butterfly,
  Cat,
  ChartBar,
  Code,
  Cow,
  Check,
  Circle,
  Clock,
  Diamond,
  Dog,
  FileText,
  Fish,
  Horse,
  Gear,
  Globe,
  Kanban,
  ListBullets,
  Link,
  ListChecks,
  Minus,
  PaperPlaneRight,
  Paperclip,
  Palette,
  Prohibit,
  PencilSimple,
  Plus,
  Rabbit,
  Question,
  SealCheck,
  Shrimp,
  Sliders,
  Sparkle,
  Stop,
  Star,
  Trash,
  Wrench,
  Warning,
  WarningCircle,
  X,
} from '@phosphor-icons/react'

export function TrashIcon({ className = 'h-4 w-4' }) {
  return <Trash className={`shrink-0 ${className}`} aria-hidden="true" />
}

/**
 * The sparkle that marks every control which spends a headless Claude call, so a
 * click that costs a minute of model time never looks like an ordinary button.
 */
export function AiSpark({ className = 'h-4 w-4' }) {
  return <Sparkle weight="fill" className={`shrink-0 ${className}`} aria-hidden="true" />
}

export const AI_CALL_TITLE = 'Runs a Claude call'

/** The chevron on a closed dropdown; flipped when the menu is open. */
export function DropdownCaret({ open, className = 'h-4 w-4' }) {
  return (
    <CaretDown
      className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''} ${className}`}
      aria-hidden="true"
    />
  )
}

export function CheckIcon({ className = 'h-3.5 w-3.5', style }) {
  return <Check weight="bold" className={`shrink-0 ${className}`} style={style} aria-hidden="true" />
}

export function EditIcon({ className = 'h-4 w-4' }) {
  return <PencilSimple className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function PlusIcon({ className = 'h-4 w-4' }) {
  return <Plus className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function StarIcon({ className = 'h-3.5 w-3.5' }) {
  return <Star weight="fill" className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function ExternalLinkIcon({ className = 'h-3.5 w-3.5' }) {
  return <ArrowUpRight className={`inline-block shrink-0 ${className}`} aria-hidden="true" />
}

/** Sort direction on a table header: which way this column is ordered, if at all. */
export function SortCaret({ order, active, className = 'h-3.5 w-3.5' }) {
  if (!active) return <CaretUpDown className={`shrink-0 ${className}`} aria-hidden="true" />
  const Glyph = order === 'asc' ? CaretUp : CaretDown
  return <Glyph weight="bold" className={`shrink-0 ${className}`} aria-hidden="true" />
}

/** Whether a listing has saved resume advice. */
export function FitDiamond({ filled, className = 'h-4 w-4' }) {
  return (
    <Diamond weight={filled ? 'fill' : 'regular'} className={`shrink-0 ${className}`} aria-hidden="true" />
  )
}

// met / partial / gap are the three verdicts Claude returns per requirement.
const STATUS_ICONS = { met: Check, partial: Minus, gap: X, unknown: Question }

export function StatusMark({ status, className = 'h-3.5 w-3.5' }) {
  const Glyph = STATUS_ICONS[status] || Question
  return <Glyph weight="bold" className={`shrink-0 ${className}`} aria-hidden="true" />
}

/** Compact tracking indicator for dense table rows. */
export function StatusCircle({ tracked, className = 'h-3 w-3' }) {
  return (
    <Circle
      weight={tracked ? 'fill' : 'regular'}
      className={`inline-block shrink-0 ${className}`}
      aria-hidden="true"
    />
  )
}

export function WarnIcon({ className = 'h-4 w-4' }) {
  return <Warning weight="fill" className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function OfflineIcon({ className = 'h-4 w-4' }) {
  return <WarningCircle weight="fill" className={`shrink-0 ${className}`} aria-hidden="true" />
}

const MODE_ICONS = { assistant: ListChecks, engineer: Code }

/** Assist vs Build, so the two are distinguishable at a glance. */
export function ModeIcon({ mode, className = 'h-4 w-4' }) {
  const Glyph = MODE_ICONS[mode] || ListChecks
  return <Glyph className={`shrink-0 ${className}`} aria-hidden="true" />
}

/**
 * The agent's icon is user-chosen, from Phosphor's animals. Barn, paw print and
 * the simple fish are left out deliberately — they are in the same category but
 * are not animals, or duplicate the fish.
 */
export const AGENT_ICONS = {
  Dog,
  Cat,
  Bird,
  Rabbit,
  Horse,
  Cow,
  Fish,
  Shrimp,
  Butterfly,
  Bug,
  BugBeetle,
}

export const AGENT_ICON_NAMES = Object.keys(AGENT_ICONS)

export function AgentIcon({ name, className = 'h-5 w-5' }) {
  const Glyph = AGENT_ICONS[name] || Dog
  return <Glyph className={`shrink-0 ${className}`} aria-hidden="true" />
}

/** A source the host refuses to serve — 403, 429 and friends. */
export function BlockedIcon({ className = 'h-4 w-4' }) {
  return <Prohibit className={`shrink-0 ${className}`} aria-hidden="true" />
}

/** The rewind arrow beside a chat message: put the files back to that point. */
export function UndoIcon({ className = 'h-4 w-4' }) {
  return <ArrowUUpLeft className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function SendIcon({ className = 'h-4 w-4' }) {
  return <PaperPlaneRight weight="fill" className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function StopIcon({ className = 'h-4 w-4' }) {
  return <Stop weight="fill" className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function LinkIcon({ className = 'h-4 w-4' }) {
  return <Link className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function AttachIcon({ className = 'h-4 w-4' }) {
  return <Paperclip className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function ToolIcon({ className = 'h-3.5 w-3.5' }) {
  return <Wrench className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function BackIcon({ className = 'h-4 w-4' }) {
  return <ArrowLeft className={`shrink-0 ${className}`} aria-hidden="true" />
}

export function ChevronIcon({ className = 'h-4 w-4' }) {
  return <CaretRight className={`shrink-0 ${className}`} aria-hidden="true" />
}

// One icon per settings section, so the index is scannable at a glance.
const SETTINGS_ICONS = {
  appearance: Palette,
  resume: FileText,
  scraper: Clock,
  claude: Sparkle,
  confirmations: SealCheck,
  tuning: Sliders,
}

export function SettingsIcon({ name, className = 'h-5 w-5' }) {
  const Glyph = SETTINGS_ICONS[name] || Gear
  return <Glyph className={`shrink-0 ${className}`} aria-hidden="true" />
}

const NAV_ICONS = {
  opportunities: ListBullets,
  applications: Kanban,
  insights: ChartBar,
  sources: Globe,
  settings: Gear,
}

export function NavIcon({ name, className = 'h-5 w-5' }) {
  const Glyph = NAV_ICONS[name] || Circle
  return <Glyph className={`shrink-0 ${className}`} aria-hidden="true" />
}
