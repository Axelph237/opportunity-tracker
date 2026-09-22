import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { CheckIcon, DropdownCaret } from './icons'
import { titleCase } from '../format'

/**
 * The app's dropdown. Replaces every native `<select>`, which could not be styled
 * to match the rest of the UI — the OS draws the popup, so it ignored the palette,
 * the mono type and the border treatment used everywhere else.
 *
 * Options are plain strings (title-cased for display) or `{ value, label }`.
 * Passing `placeholder` adds a leading entry that clears the value, which is how
 * the filter bars express "no filter".
 *
 * Keyboard: Enter/Space/Arrow opens, Up/Down/Home/End move, Enter picks, Escape
 * closes, and typing jumps to the first label starting with what you typed.
 */
export default function Dropdown({
  value,
  onChange,
  options = [],
  placeholder,
  className = 'w-auto',
  buttonClassName = '',
  disabled,
  ariaLabel,
  align = 'left',
  variant = 'field',
  panelClassName = '',
  header,
  hint,
}) {
  const entries = [
    ...(placeholder ? [{ value: '', label: placeholder, isPlaceholder: true }] : []),
    ...options.map((option) =>
      typeof option === 'string' ? { value: option, label: titleCase(option) } : option,
    ),
  ]

  const current = value === undefined || value === null ? '' : String(value)
  const selectedIndex = entries.findIndex((entry) => String(entry.value) === current)
  const selected = selectedIndex >= 0 ? entries[selectedIndex] : null

  const showIconColumn = entries.some((entry) => entry.icon)

  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(Math.max(selectedIndex, 0))
  const [dropUp, setDropUp] = useState(false)
  const rootRef = useRef(null)
  const listRef = useRef(null)
  const buttonRef = useRef(null)
  const typeahead = useRef({ text: '', at: 0 })
  const listId = useId()

  const close = useCallback((refocus = true) => {
    setOpen(false)
    if (refocus) buttonRef.current?.focus()
  }, [])

  const pick = (entry) => {
    onChange(entry.isPlaceholder ? undefined : entry.value)
    close()
  }

  // Close when the click lands anywhere else, including inside other panels.
  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  // Open upwards when the menu would not fit below — the Applications panel and
  // the pinned filter bars both sit close to the bottom of their scroll area.
  useLayoutEffect(() => {
    if (!open) return
    const trigger = buttonRef.current?.getBoundingClientRect()
    if (!trigger) return
    const needed = Math.min(entries.length * 34 + 8, 260)
    setDropUp(window.innerHeight - trigger.bottom < needed && trigger.top > needed)
  }, [open, entries.length])

  useEffect(() => {
    if (!open) return
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0)
  }, [open, selectedIndex])

  useEffect(() => {
    if (!open) return
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [open, activeIndex])

  const move = (delta) => {
    if (!entries.length) return
    setActiveIndex((index) => (index + delta + entries.length) % entries.length)
  }

  const onKeyDown = (event) => {
    if (disabled) return
    if (!open) {
      if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) {
        event.preventDefault()
        setOpen(true)
      }
      return
    }
    switch (event.key) {
      case 'Escape':
        event.preventDefault()
        // SlidePanel and the confirm dialog both close on a window-level Escape.
        // Without this the key would dismiss the menu and the panel holding it,
        // losing whatever was typed into the form.
        event.stopPropagation()
        close()
        break
      case 'Tab':
        setOpen(false)
        break
      case 'ArrowDown':
        event.preventDefault()
        move(1)
        break
      case 'ArrowUp':
        event.preventDefault()
        move(-1)
        break
      case 'Home':
        event.preventDefault()
        setActiveIndex(0)
        break
      case 'End':
        event.preventDefault()
        setActiveIndex(entries.length - 1)
        break
      case 'Enter':
      case ' ':
        event.preventDefault()
        if (entries[activeIndex]) pick(entries[activeIndex])
        break
      default: {
        if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return
        const now = Date.now()
        const text = (now - typeahead.current.at < 700 ? typeahead.current.text : '') + event.key.toLowerCase()
        typeahead.current = { text, at: now }
        const match = entries.findIndex((entry) => entry.label.toLowerCase().startsWith(text))
        if (match >= 0) setActiveIndex(match)
      }
    }
  }

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={onKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ariaLabel}
        className={
          variant === 'inline'
            ? // Compact pill for toolbars, where a full-width field would dominate.
              `inline-flex items-center gap-1 rounded px-2 py-1 transition-colors disabled:opacity-45 ${
                open
                  ? 'bg-surface-container-high text-on-surface'
                  : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
              } ${buttonClassName}`
            : `field flex w-full items-center justify-between gap-2 text-left disabled:cursor-not-allowed disabled:opacity-45 ${
                open ? 'border-primary' : ''
              } ${buttonClassName}`
        }
      >
        {/* Inline triggers show the selected option's icon; field triggers stay text-only. */}
        {variant === 'inline' && selected?.icon ? selected.icon : null}
        <span
          className={`truncate ${
            variant === 'inline'
              ? ''
              : selected && !selected.isPlaceholder
                ? 'text-on-surface'
                : 'text-on-surface-variant'
          }`}
        >
          {selected ? selected.label : placeholder || 'Select…'}
        </span>
        <DropdownCaret open={open} className={variant === 'inline' ? 'h-3.5 w-3.5' : 'h-4 w-4 text-on-surface-variant'} />
      </button>

      {open ? (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          tabIndex={-1}
          aria-activedescendant={`${listId}-${activeIndex}`}
          className={`absolute z-30 max-h-80 min-w-full overflow-auto rounded-lg border border-outline-variant bg-surface-container p-1.5 shadow-xl shadow-black/40 animate-fade-in ${
            dropUp ? 'bottom-full mb-2' : 'top-full mt-2'
          } ${align === 'right' ? 'right-0' : 'left-0'} ${panelClassName}`}
        >
          {header || hint ? (
            <li className="flex items-center justify-between gap-6 px-2 pb-2 pt-1">
              {header ? <span className="label-data">{header}</span> : <span />}
              {hint ? (
                <span className="flex items-center gap-1 whitespace-nowrap text-on-surface-variant">
                  {hint.keys?.map((key, index) => (
                    <span key={key} className="contents">
                      {/* `join` is for chords like ⇧ + tab; alternatives such as ↑ ↓ read better bare. */}
                      {index > 0 && hint.join ? <span aria-hidden="true">{hint.join}</span> : null}
                      <kbd className="rounded border border-outline-variant bg-surface-container-high px-1.5 py-0.5 font-mono text-data text-on-surface">
                        {key}
                      </kbd>
                    </span>
                  ))}
                  {hint.text ? <span className="text-data">{hint.text}</span> : null}
                </span>
              ) : null}
            </li>
          ) : null}

          {entries.length === 0 ? (
            <li className="px-2 py-2 font-mono text-data text-on-surface-variant">No options</li>
          ) : null}

          {entries.map((entry, index) => {
            const isSelected = String(entry.value) === current
            const highlighted = isSelected || index === activeIndex
            return (
              <li
                key={`${entry.value}-${index}`}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={isSelected}
                data-active={index === activeIndex}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={(event) => {
                  // Several of these menus sit inside a <label>. An <li> is not
                  // interactive content, so without this the browser forwards the
                  // click on to the label's control — the trigger — which reopens
                  // the menu the instant it closes.
                  event.preventDefault()
                  pick(entry)
                }}
                className={`mt-0.5 flex cursor-pointer items-start gap-3 rounded-md px-2 transition-colors first:mt-0 ${
                  entry.description ? 'py-2.5' : 'whitespace-nowrap py-1.5'
                } ${highlighted ? 'bg-surface-container-high' : ''} ${
                  entry.isPlaceholder ? 'italic' : ''
                }`}
              >
                {showIconColumn ? (
                  <span
                    className={`flex w-5 shrink-0 justify-center ${
                      entry.description ? 'mt-0.5' : ''
                    } ${isSelected ? 'text-on-surface' : 'text-on-surface-variant'}`}
                  >
                    {entry.icon ?? null}
                  </span>
                ) : null}

                <span className="min-w-0 flex-1">
                  <span className={`block ${isSelected ? 'text-on-surface' : 'text-on-surface'}`}>
                    {entry.label}
                  </span>
                  {entry.description ? (
                    <span className="mt-1 block leading-snug text-on-surface-variant">
                      {entry.description}
                    </span>
                  ) : null}
                </span>

                {/* The tick sits at the trailing edge, so the icon column stays
                    aligned whether or not a row is the current value. */}
                <CheckIcon
                  className={`shrink-0 ${entry.description ? 'mt-1' : 'mt-[3px]'} ${
                    isSelected ? 'opacity-100 text-on-surface' : 'opacity-0'
                  }`}
                />
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}
