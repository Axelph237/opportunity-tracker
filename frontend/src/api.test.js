import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiOfflineError, OFFLINE_MESSAGE, api } from './api'

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('request URL/method building', () => {
  it('GET: builds a plain path with the /api base', async () => {
    fetch.mockResolvedValue(jsonResponse({ ok: true }))
    await api.stats()
    expect(fetch).toHaveBeenCalledWith('/api/stats', expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }))
  })

  it('GET: serializes query params, dropping undefined/null/empty and repeating arrays', async () => {
    fetch.mockResolvedValue(jsonResponse([]))
    await api.opportunities({ search: 'ml', type: ['job', 'internship'], skip_me: undefined, also_skip: null, and_this: '' })
    const [url] = fetch.mock.calls[0]
    expect(url).toBe('/api/opportunities?search=ml&type=job&type=internship')
  })

  it('POST: sends a JSON body and the POST method', async () => {
    fetch.mockResolvedValue(jsonResponse({ id: 1 }))
    await api.createSource({ name: 'ACME', url: 'https://acme.example' })
    expect(fetch).toHaveBeenCalledWith('/api/sources', {
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
      body: JSON.stringify({ name: 'ACME', url: 'https://acme.example' }),
    })
  })

  it('POST with no body: omits the body entirely (used for fire-and-forget actions)', async () => {
    fetch.mockResolvedValue(jsonResponse({ ok: true }))
    await api.runScrape()
    expect(fetch).toHaveBeenCalledWith('/api/scrape/run-now', {
      headers: { 'Content-Type': 'application/json' },
      method: 'POST',
      body: undefined,
    })
  })

  it('PATCH: sends a JSON body and the PATCH method', async () => {
    fetch.mockResolvedValue(jsonResponse({ id: 5 }))
    await api.updateSource(5, { active: false })
    expect(fetch).toHaveBeenCalledWith('/api/sources/5', {
      headers: { 'Content-Type': 'application/json' },
      method: 'PATCH',
      body: JSON.stringify({ active: false }),
    })
  })

  it('DELETE: sends the DELETE method with no body', async () => {
    fetch.mockResolvedValue(new Response(null, { status: 204 }))
    await api.deleteSource(9)
    expect(fetch).toHaveBeenCalledWith('/api/sources/9', {
      headers: { 'Content-Type': 'application/json' },
      method: 'DELETE',
    })
  })

  it('204 No Content resolves to null instead of trying to parse a body', async () => {
    fetch.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(api.deleteSource(1)).resolves.toBeNull()
  })

  it('a FormData body is sent without forcing a JSON content-type header', async () => {
    fetch.mockResolvedValue(jsonResponse({ ok: true }))
    const file = new File(['hello'], 'resume.pdf', { type: 'application/pdf' })
    await api.uploadResume(file)
    const [url, options] = fetch.mock.calls[0]
    expect(url).toBe('/api/settings/resume')
    expect(options.method).toBe('POST')
    expect(options.headers).toBeUndefined()
    expect(options.body).toBeInstanceOf(FormData)
    expect(options.body.get('file')).toBe(file)
  })
})

describe('error handling', () => {
  it('surfaces the JSON `detail` string from an error response', async () => {
    fetch.mockResolvedValue(jsonResponse({ detail: 'Source URL already tracked' }, { status: 400 }))
    await expect(api.createSource({})).rejects.toThrow('Source URL already tracked')
  })

  it('stringifies a non-string `detail` (e.g. FastAPI validation errors)', async () => {
    const detail = [{ loc: ['body', 'url'], msg: 'field required' }]
    fetch.mockResolvedValue(jsonResponse({ detail }, { status: 422 }))
    await expect(api.createSource({})).rejects.toThrow(JSON.stringify(detail))
  })

  it('falls back to "status statusText" when the error body has no JSON', async () => {
    fetch.mockResolvedValue(new Response('not json', { status: 500, statusText: 'Internal Server Error' }))
    await expect(api.stats()).rejects.toThrow('500 Internal Server Error')
  })

  it('a rejected `ok` response throws a plain Error, not ApiOfflineError', async () => {
    fetch.mockResolvedValue(jsonResponse({ detail: 'nope' }, { status: 400 }))
    await expect(api.stats()).rejects.not.toBeInstanceOf(ApiOfflineError)
  })

  it('502/503/504 from the dev proxy are treated as the backend being offline', async () => {
    fetch.mockResolvedValue(jsonResponse({ detail: 'Backend not reachable' }, { status: 503 }))
    await expect(api.stats()).rejects.toBeInstanceOf(ApiOfflineError)
  })

  it('a transport-level fetch failure (backend/dev server not running) is reported as offline', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    const error = await api.stats().catch((error_) => error_)
    expect(error).toBeInstanceOf(ApiOfflineError)
    expect(error.message).toContain(OFFLINE_MESSAGE)
    expect(error.message).toContain('Failed to fetch')
  })
})

describe('api.resumePdfUrl', () => {
  it('addresses the render plainly', () => {
    expect(api.resumePdfUrl(7)).toBe('/api/resumes/7/pdf')
  })

  it('asks for an attachment when downloading', () => {
    expect(api.resumePdfUrl(7, { download: true })).toContain('download=true')
  })

  it('carries a cache key the server can see', () => {
    // In the query, not a fragment: a fragment never reaches the server, so a
    // stale render would keep being served after a recompile.
    expect(api.resumePdfUrl(7, { version: 'abc' })).toBe('/api/resumes/7/pdf?v=abc')
  })
})
