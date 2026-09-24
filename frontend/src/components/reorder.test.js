import { describe, expect, it } from 'vitest'
import { moved, reconcile } from './reorder'

const DEFAULTS = ['a', 'b', 'c', 'd']

describe('reconcile', () => {
  it('uses the remembered order when it still matches', () => {
    expect(reconcile(['d', 'a', 'c', 'b'], DEFAULTS)).toEqual(['d', 'a', 'c', 'b'])
  })

  it('falls back to the shipped order when nothing was remembered', () => {
    expect(reconcile(null, DEFAULTS)).toEqual(DEFAULTS)
    expect(reconcile(undefined, DEFAULTS)).toEqual(DEFAULTS)
    expect(reconcile([], DEFAULTS)).toEqual(DEFAULTS)
  })

  it('ignores a stored value that is not a list at all', () => {
    expect(reconcile('b,a', DEFAULTS)).toEqual(DEFAULTS)
    expect(reconcile({ 0: 'a' }, DEFAULTS)).toEqual(DEFAULTS)
  })

  it('drops a section the app no longer has', () => {
    expect(reconcile(['c', 'gone', 'a', 'b', 'd'], DEFAULTS)).toEqual(['c', 'a', 'b', 'd'])
  })

  it('keeps a section added after the order was saved', () => {
    // The whole point of reconciling. Shipping a new tab must not hide it from
    // everyone who had already rearranged their sidebar.
    expect(reconcile(['d', 'c', 'b', 'a'], [...DEFAULTS, 'e'])).toEqual(['d', 'c', 'b', 'a', 'e'])
  })

  it('leaves a hand-picked order alone when a new section arrives', () => {
    // On the end, even though it ships in the middle: an upgrade must not
    // rearrange an order someone set deliberately.
    expect(reconcile(['c', 'a'], ['a', 'new', 'c'])).toEqual(['c', 'a', 'new'])
  })

  it('survives a duplicated entry', () => {
    expect(reconcile(['b', 'b', 'a'], DEFAULTS)).toEqual(['b', 'a', 'c', 'd'])
  })

  it('never loses or invents a section', () => {
    for (const saved of [null, ['x'], ['d'], ['b', 'b'], DEFAULTS.slice().reverse()]) {
      expect([...reconcile(saved, DEFAULTS)].sort()).toEqual([...DEFAULTS].sort())
    }
  })
})

describe('moved', () => {
  it('lifts an item out and puts it back at the index asked for', () => {
    expect(moved(DEFAULTS, 'a', 2)).toEqual(['b', 'c', 'a', 'd'])
    expect(moved(DEFAULTS, 'd', 0)).toEqual(['d', 'a', 'b', 'c'])
  })

  it('returns the very same array when nothing would change', () => {
    // Identity, not just equality: a drag fires these by the dozen, and a new
    // array each time would re-render the sidebar on every one.
    expect(moved(DEFAULTS, 'a', 0)).toBe(DEFAULTS)
    expect(moved(DEFAULTS, 'a', -1)).toBe(DEFAULTS)
    expect(moved(DEFAULTS, 'a', 4)).toBe(DEFAULTS)
    expect(moved(DEFAULTS, 'nope', 1)).toBe(DEFAULTS)
  })

  it('does not mutate what it was given', () => {
    const before = [...DEFAULTS]
    moved(DEFAULTS, 'a', 3)
    expect(DEFAULTS).toEqual(before)
  })
})
