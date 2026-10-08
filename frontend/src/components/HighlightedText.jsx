// Same tone as the `skill_matches` chips on OpportunityCard, so a keyword the
// coverage panel calls covered looks the same wherever it turns up.
const MARK =
  'rounded border border-primary/40 bg-primary/10 px-2 py-[2px] font-mono text-data text-primary'

const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * One pattern for the whole term list, longest first.
 *
 * Longest first so an overlap resolves to the more specific term: with
 * "machine learning" and "learning" both in the ad, the phrase is what the
 * reader wants marked, not the word inside it.
 */
function buildPattern(terms) {
  const unique = [
    ...new Set((terms || []).filter((term) => typeof term === 'string' && term.trim())),
  ].sort((a, b) => b.length - a.length)
  if (!unique.length) return null

  const alternatives = unique
    // A space in the term has to match a line break or a run of spaces in the
    // bullet: the ad and the resume wrap in different places.
    .map((term) => escapeRegex(term.trim()).replace(/\s+/g, '\\s+'))
    .join('|')

  // Not `\b`: it reads `+` as a boundary, so it puts one in the middle of
  // "C++" and refuses one after it — the terms that most need marking are
  // exactly the ones it gets wrong. Alphanumeric lookarounds instead.
  return new RegExp(`(?<![A-Za-z0-9])(?:${alternatives})(?![A-Za-z0-9])`, 'gi')
}

/**
 * `text` with every occurrence of `terms` wrapped in a `<mark>`.
 *
 * Nodes, never a string of HTML. Everything this marks up is either a scraped
 * job ad or text pasted out of one, React's raw-HTML escape hatch is used
 * nowhere in this app, and keeping it that way is the whole reason this is a
 * component rather than a replace() over a template string.
 */
export default function HighlightedText({ text, terms = [] }) {
  const source = typeof text === 'string' ? text : ''
  const pattern = buildPattern(terms)
  if (!pattern) return source

  const nodes = []
  let cursor = 0
  for (const match of source.matchAll(pattern)) {
    if (match.index > cursor) nodes.push(source.slice(cursor, match.index))
    nodes.push(
      <mark key={match.index} className={MARK}>
        {match[0]}
      </mark>,
    )
    cursor = match.index + match[0].length
  }
  if (!nodes.length) return source
  if (cursor < source.length) nodes.push(source.slice(cursor))
  return nodes
}
