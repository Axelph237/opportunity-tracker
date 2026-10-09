import { EditIcon } from './icons'

/**
 * The heading the compiled resume prints, shown where it prints.
 *
 * Editable from here because this is the one place the user is looking at the
 * document as a whole. What it edits is one record for the whole app, not
 * something belonging to this draft, which the empty state says out loud.
 */
export default function ContactBlock({ contact, onEdit }) {
  const reach = [contact?.location, contact?.email, contact?.phone].filter(Boolean)
  const links = (contact?.links || []).filter((link) => link.url)
  const filled = Boolean(contact?.name || reach.length || links.length)

  return (
    <section className="group/contact rounded border border-outline-variant bg-surface-container px-3 py-2.5">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 text-center">
          {filled ? (
            <>
              {contact.name ? (
                <div className="text-base font-semibold text-on-surface">{contact.name}</div>
              ) : null}
              {reach.length ? (
                <div className="font-mono text-data text-on-surface-variant">{reach.join(' · ')}</div>
              ) : null}
              {links.length ? (
                <div className="font-mono text-data text-primary">
                  {links.map((link) => link.label || link.url).join(' · ')}
                </div>
              ) : null}
            </>
          ) : (
            <button
              type="button"
              className="font-mono text-data text-on-surface-variant underline-offset-2 hover:text-primary hover:underline"
              title="Printed at the top of every resume you build"
              onClick={onEdit}
            >
              Add your name and contact details
            </button>
          )}
        </div>
        <button
          type="button"
          aria-label="Edit your contact details"
          title="Shared by every resume you build"
          className="shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-primary focus-visible:opacity-100 group-hover/contact:opacity-100"
          onClick={onEdit}
        >
          <EditIcon />
        </button>
      </div>
    </section>
  )
}
