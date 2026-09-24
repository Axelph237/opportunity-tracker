/**
 * A small hover label drawn by the app rather than the browser.
 *
 * `title` is the obvious alternative, but the OS decides when it appears, how
 * long it waits and what it looks like — and it is skipped entirely on controls
 * that are inert, which is exactly where this is needed: the undo arrow beside a
 * message with nothing to undo explains itself on hover instead of doing nothing.
 *
 * Purely CSS, on a named group so it never fights the surrounding `group`
 * (message rows use one to reveal the arrow in the first place).
 */
const PLACEMENT = {
  top: 'bottom-full left-1/2 mb-1.5 -translate-x-1/2 text-center',
  // Anchored by its right edge instead of its centre, for controls that sit
  // against the right edge of a scroll container and would clip a centred one.
  'top-end': 'bottom-full right-0 mb-1.5 text-right',
  bottom: 'top-full left-1/2 mt-1.5 -translate-x-1/2 text-center',
  left: 'right-full top-1/2 mr-2 -translate-y-1/2 text-right',
  right: 'left-full top-1/2 ml-2 -translate-y-1/2',
}

export default function Tooltip({ label, children, placement = 'top', className = '' }) {
  if (!label) return children
  // `className` styles the wrapper but must not position it — the anchor has to
  // stay `relative` for the bubble to hang off it. Position the caller's own
  // element around this instead.
  return (
    <span className={`group/tip relative inline-flex ${className}`}>
      {children}
      <span
        role="tooltip"
        // `:has(:focus-visible)` rather than `:focus-within`. A click leaves
        // focus on the thing you clicked, so focus-within kept the bubble up
        // after the pointer had gone — until you clicked somewhere else. The
        // browser only matches `:focus-visible` when it would draw a focus
        // ring, so keyboard users still get the label and mouse users do not
        // get a tooltip stuck to a link they just followed.
        className={`pointer-events-none absolute z-40 w-max max-w-[18rem] rounded-md border border-outline-variant bg-surface-container px-2 py-1 text-data leading-snug text-on-surface opacity-0 shadow-lg shadow-black/30 transition-opacity delay-100 group-hover/tip:opacity-100 group-has-focus-visible/tip:opacity-100 ${
          PLACEMENT[placement] || PLACEMENT.top
        }`}
      >
        {label}
      </span>
    </span>
  )
}
