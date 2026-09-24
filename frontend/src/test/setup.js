import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom does not implement layout, so it has no scrollIntoView. Several
// components (Dropdown among them) call it on the active option when
// navigating with the keyboard; without a stub every such interaction throws.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

/*
 * Give jsdom a `PointerEvent`.
 *
 * jsdom does not implement it, so Testing Library's `fireEvent.pointerDown`
 * falls back to a plain `Event` and silently drops `clientX`/`clientY` — a
 * drag test then reads `undefined` coordinates and computes NaN. Extending
 * `MouseEvent` is enough: it already carries the coordinates, and the resize
 * handles only need `pointerId` beyond that.
 */
if (typeof window !== 'undefined' && typeof window.PointerEvent === 'undefined') {
  class PointerEvent extends window.MouseEvent {
    constructor(type, params = {}) {
      super(type, params)
      this.pointerId = params.pointerId ?? 0
      this.pointerType = params.pointerType ?? 'mouse'
      this.isPrimary = params.isPrimary ?? true
    }
  }
  window.PointerEvent = PointerEvent
  globalThis.PointerEvent = PointerEvent
}

// Pointer capture keeps a drag alive when the cursor outruns the handle. jsdom
// has no layout and so no capture; the components call these optionally, but
// defining them keeps the code path identical to a real browser.
if (typeof Element !== 'undefined' && !Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {}
  Element.prototype.releasePointerCapture = () => {}
  Element.prototype.hasPointerCapture = () => false
}

// jsdom implements no layout and so no ResizeObserver. The PDF preview uses
// one to size its canvases to the pane; without a stub the component throws on
// mount. Observing nothing is fine — the tests drive the width directly.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

/*
 * Guarantee a usable `localStorage`.
 *
 * Node 22.4+ ships an experimental global `localStorage` that shadows the one
 * jsdom installs, leaving neither usable under Vitest. The obvious fix —
 * `NODE_OPTIONS=--no-experimental-webstorage` in the npm script — works on new
 * Node and makes `npm test` fail outright on Node 18 and 20, where the flag
 * does not exist and an unrecognised NODE_OPTIONS entry is fatal. install.sh
 * accepts Node 18, so the test command has to work there too.
 *
 * A small in-memory Storage is portable across all of them.
 */
function workingStorage(candidate) {
  try {
    if (!candidate || typeof candidate.getItem !== 'function') return false
    candidate.setItem('__probe__', '1')
    candidate.removeItem('__probe__')
    return true
  } catch {
    return false
  }
}

if (!workingStorage(globalThis.localStorage)) {
  const store = new Map()
  const storage = {
    get length() {
      return store.size
    },
    key: (index) => [...store.keys()][index] ?? null,
    getItem: (key) => (store.has(String(key)) ? store.get(String(key)) : null),
    setItem: (key, value) => void store.set(String(key), String(value)),
    removeItem: (key) => void store.delete(String(key)),
    clear: () => store.clear(),
  }
  for (const target of [globalThis, typeof window === 'undefined' ? null : window]) {
    if (target) Object.defineProperty(target, 'localStorage', { configurable: true, value: storage })
  }
}

afterEach(() => {
  cleanup()
  localStorage.clear()
})
