import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Markdown from './Markdown'

const html = (markdown) => render(<Markdown>{markdown}</Markdown>).container

describe('Markdown', () => {
  it('renders nothing for empty or missing content', () => {
    expect(render(<Markdown>{''}</Markdown>).container).toBeEmptyDOMElement()
    expect(render(<Markdown>{null}</Markdown>).container).toBeEmptyDOMElement()
  })

  it('renders paragraphs, emphasis and strong text', () => {
    const c = html('Plain **bold** and *italic* text.')
    expect(c.querySelector('strong')).toHaveTextContent('bold')
    expect(c.querySelector('em')).toHaveTextContent('italic')
  })

  it('renders bullet and numbered lists', () => {
    expect(html('- one\n- two').querySelectorAll('ul li')).toHaveLength(2)
    expect(html('1. first\n2. second').querySelectorAll('ol li')).toHaveLength(2)
  })

  it('caps heading levels so a reply cannot dwarf the conversation', () => {
    const c = html('# Top level')
    expect(c.querySelector('h1')).toBeNull()
    expect(c.querySelector('h3')).toHaveTextContent('Top level')
  })

  describe('code', () => {
    it('gives inline code the chip treatment', () => {
      const code = html('Run `npm test` now.').querySelector('code')
      expect(code).toHaveClass('md-code')
      expect(code.parentElement.tagName).toBe('P')
    })

    it('puts a fenced block in a scrollable pre', () => {
      const c = html('```\nline one\nline two\n```')
      const pre = c.querySelector('pre')
      expect(pre).toHaveClass('overflow-x-auto')
      expect(pre.querySelector('code')).toHaveTextContent('line one')
    })

    it('handles a fence with a language the same way', () => {
      const c = html('```python\nx = 1\n```')
      expect(c.querySelector('pre code')).toHaveTextContent('x = 1')
    })
  })

  describe('GitHub flavoured markdown', () => {
    it('renders tables', () => {
      const c = html('| Source | Status |\n|---|---|\n| IEEE | Blocked |')
      expect(c.querySelectorAll('th')).toHaveLength(2)
      expect(c.querySelector('td')).toHaveTextContent('IEEE')
    })

    it('renders strikethrough', () => {
      expect(html('~~gone~~').querySelector('del')).toHaveTextContent('gone')
    })

    it('renders task lists as read-only checkboxes', () => {
      const boxes = html('- [x] done\n- [ ] todo').querySelectorAll('input[type=checkbox]')
      expect(boxes).toHaveLength(2)
      expect(boxes[0].checked).toBe(true)
      expect(boxes[1].checked).toBe(false)
      expect(boxes[0]).toHaveAttribute('readonly')
    })

    it('autolinks bare URLs', () => {
      const link = html('See https://example.com/jobs for more.').querySelector('a')
      expect(link).toHaveAttribute('href', 'https://example.com/jobs')
    })
  })

  describe('safety', () => {
    // The agent quotes text it has read from scraped job pages. Anything in a
    // reply may have originated on a site we do not control.
    it('escapes raw HTML rather than rendering it', () => {
      const c = html('Before <img src=x onerror="alert(1)"> after')
      // No element is created, and nothing carries the handler as an attribute.
      // The characters still appear in innerHTML — as escaped text, which is
      // exactly the point, so asserting on the markup string would pass for the
      // wrong reason.
      expect(c.querySelector('img')).toBeNull()
      expect(c.querySelector('[onerror]')).toBeNull()
      expect(c.textContent).toContain('<img src=x onerror="alert(1)">')
    })

    it('does not execute an inline script tag', () => {
      const c = html('<script>window.__pwned = true</script>')
      expect(c.querySelector('script')).toBeNull()
      expect(window.__pwned).toBeUndefined()
    })

    it('does not fetch markdown images, showing the alt text instead', () => {
      const c = html('![a diagram](https://tracker.example.com/pixel.png)')
      expect(c.querySelector('img')).toBeNull()
      expect(c.textContent).toContain('[image: a diagram]')
    })

    it('opens links away from the app, with no window.opener', () => {
      const link = html('[a listing](https://example.com)').querySelector('a')
      expect(link).toHaveAttribute('target', '_blank')
      expect(link.getAttribute('rel')).toContain('noopener')
      expect(link.getAttribute('rel')).toContain('noreferrer')
    })
  })

  it('renders plain text unchanged when it contains no markdown', () => {
    render(<Markdown>{'I tagged 12 listings in Chicago.'}</Markdown>)
    expect(screen.getByText('I tagged 12 listings in Chicago.')).toBeInTheDocument()
  })
})
