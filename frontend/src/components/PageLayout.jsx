import { NavIcon } from './icons'

/**
 * Full-height page frame.
 *
 * The heading, the action buttons and the filter bar are pinned; only `children`
 * scrolls. Long tables therefore scroll inside themselves instead of pushing the
 * page title off the screen.
 *
 * `icon` is usually a nav-icon name, and this decides its size and tone so that
 * every page heading matches without each one repeating the classes. A node is
 * accepted too, for the agent, whose icon the user chooses.
 */
export default function PageLayout({
  title,
  icon,
  description,
  actions,
  toolbar,
  error,
  banner,
  scroll = true,
  contentClassName = '',
  children,
}) {
  const glyph =
    typeof icon === 'string' ? (
      <NavIcon name={icon} className="h-6 w-6 text-on-surface-variant" />
    ) : (
      icon
    )

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-outline-variant bg-surface px-8 pt-8">
        <header className="flex flex-wrap items-start justify-between gap-4 pb-4">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2.5">
              {glyph}
              {title}
            </h1>
            {description ? <p className="mt-1 text-on-surface-variant">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
        </header>
        {banner}
        {error ? (
          <div className="mb-4 rounded border border-error/60 bg-error/10 px-4 py-2 text-error">{error}</div>
        ) : null}
        {toolbar}
      </div>

      <div
        className={`min-h-0 flex-1 px-8 ${
          scroll ? 'overflow-auto' : 'flex flex-col overflow-hidden'
        } ${contentClassName}`}
      >
        {children}
      </div>
    </div>
  )
}
