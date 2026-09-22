import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * Renders the agent's replies, which arrive as markdown.
 *
 * Every element is mapped explicitly rather than styled with a prose plugin, so
 * the output uses the same MD3 tokens as the rest of the app and re-themes with
 * it. Sizes are deliberately restrained: a reply is a chat bubble, so an `# H1`
 * that dwarfs the conversation is wrong even though it is valid markdown.
 *
 * Raw HTML is NOT enabled. react-markdown escapes it by default and that stays
 * the case here — the agent quotes text it has read from scraped job pages, and
 * rendering that as HTML would make any one of them able to inject markup into
 * this window.
 */

const COMPONENTS = {
  p: ({ children }) => <p className="my-2 leading-relaxed first:mt-0 last:mb-0">{children}</p>,

  h1: ({ children }) => <h3 className="mb-2 mt-4 font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-4 font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1.5 mt-3 font-semibold first:mt-0">{children}</h4>,
  h4: ({ children }) => (
    <h5 className="label-data mb-1.5 mt-3 first:mt-0">{children}</h5>
  ),
  h5: ({ children }) => <h5 className="label-data mb-1.5 mt-3 first:mt-0">{children}</h5>,
  h6: ({ children }) => <h6 className="label-data mb-1.5 mt-3 first:mt-0">{children}</h6>,

  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-5 first:mt-0 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5 first:mt-0 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed marker:text-on-surface-variant">{children}</li>,

  a: ({ href, children }) => (
    // Anything the agent links to is outside this app, so it opens away from it.
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-primary underline underline-offset-2 hover:no-underline"
    >
      {children}
    </a>
  ),

  strong: ({ children }) => <strong className="font-semibold text-on-surface">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  del: ({ children }) => <del className="text-on-surface-variant line-through">{children}</del>,

  // react-markdown dropped the `inline` prop in v10, and a fence without a
  // language carries no className either — so there is no reliable prop to
  // branch on. Both cases render the same element and CSS tells them apart by
  // whether they sit inside a <pre>; see `.md-code` in index.css.
  code: ({ children }) => <code className="md-code font-code text-data">{children}</code>,

  // A long command must not stretch the bubble; it scrolls inside its own block.
  pre: ({ children }) => (
    <pre className="my-2.5 overflow-x-auto rounded-lg border border-outline-variant bg-surface px-3 py-2.5 first:mt-0 last:mb-0">
      {children}
    </pre>
  ),

  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-outline-variant pl-3 text-on-surface-variant">
      {children}
    </blockquote>
  ),

  hr: () => <hr className="my-3 border-outline-variant" />,

  table: ({ children }) => (
    <div className="my-2.5 overflow-x-auto first:mt-0 last:mb-0">
      <table className="w-full border-collapse text-left">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-outline-variant">{children}</thead>,
  th: ({ children }) => <th className="label-data px-2 py-1.5 align-top">{children}</th>,
  td: ({ children }) => (
    <td className="border-b border-outline-variant/50 px-2 py-1.5 align-top">{children}</td>
  ),

  input: ({ checked, type }) =>
    // GFM task lists. Rendered read-only: it is a transcript, not a form.
    type === 'checkbox' ? (
      <input type="checkbox" checked={!!checked} readOnly className="mr-1.5 accent-primary" />
    ) : null,

  img: ({ alt }) => (
    // Images are not fetched. The agent has no reason to embed one, and a
    // remote URL in a reply would be a way to phone home from this window.
    <span className="font-mono text-data text-on-surface-variant">[image: {alt || 'untitled'}]</span>
  ),
}

export default function Markdown({ children, className = '' }) {
  if (!children) return null
  return (
    <div className={`min-w-0 break-words text-on-surface ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
