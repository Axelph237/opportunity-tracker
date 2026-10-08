import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiOfflineError, api } from './api'

function answers({ status = 200, body = {}, ok = status < 400 } = {}) {
  global.fetch = vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: 'Conflict',
    json: async () => body,
    headers: new Headers(),
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('api / what an error answer carries', () => {
  it('puts the status and the parsed detail on the error it throws', async () => {
    // A 409 from a push is not a failure to report. It carries the diff the
    // page has to show before it offers to overwrite anything, and a caller
    // that only sees the message would have to parse it back out of a string.
    answers({ status: 409, body: { detail: { diverged: true, current_latex: '% by hand' } } })

    const error = await api.pushDraft(9).catch((caught) => caught)

    expect(error.status).toBe(409)
    expect(error.detail).toEqual({ diverged: true, current_latex: '% by hand' })
  })

  it('uses a string detail as the message', async () => {
    answers({ status: 400, body: { detail: 'There is no job post 999 to attach this draft to.' } })

    const error = await api.createDraft({}).catch((caught) => caught)

    expect(error.message).toBe('There is no job post 999 to attach this draft to.')
    expect(error.status).toBe(400)
  })

  it('still calls a dead proxy offline rather than an answer', async () => {
    answers({ status: 503, body: { detail: 'no engine' } })

    await expect(api.drafts()).rejects.toBeInstanceOf(ApiOfflineError)
  })
})
