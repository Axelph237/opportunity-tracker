import { useState } from 'react'
import { SiteIcon } from './icons'

/** The hostname an icon is looked up by. Must match the server's rule. */
export function domainOf(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/^www\./, '')
  } catch {
    return null
  }
}

/**
 * The site's own icon, standing in for the row it belongs to.
 *
 * Falls back to a neutral glyph whenever there is nothing to show — a URL that
 * will not parse, a site with no icon, a first load still fetching. A row must
 * never be left with a broken-image box where its identity should be.
 */
export default function Favicon({ url, className = 'h-5 w-5' }) {
  const [failed, setFailed] = useState(false)
  const domain = domainOf(url)

  if (!domain || failed) {
    return <SiteIcon className={`${className} shrink-0 text-on-surface-variant`} />
  }

  return (
    <img
      src={`/api/favicons/${encodeURIComponent(domain)}`}
      alt=""
      // Decorative: the row already names the organisation, so announcing the
      // logo as well would just be noise.
      aria-hidden="true"
      loading="lazy"
      onError={() => setFailed(true)}
      className={`${className} shrink-0 rounded-sm object-contain`}
    />
  )
}
