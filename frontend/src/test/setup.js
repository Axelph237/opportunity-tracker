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
