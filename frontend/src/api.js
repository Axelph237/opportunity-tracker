// Thin fetch wrapper. Vite proxies /api to the FastAPI backend on :8000.

const BASE = '/api'

export const OFFLINE_MESSAGE =
  'Backend not reachable. Start it with: .venv/bin/python -m uvicorn main:app --app-dir backend --reload'

/** Thrown when the API could not be reached at all, as opposed to answering an error. */
export class ApiOfflineError extends Error {}

async function send(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: options.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (error) {
    // fetch only rejects on a transport failure, so the dev server itself is down.
    throw new ApiOfflineError(`${OFFLINE_MESSAGE} (${error.message})`)
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* response had no JSON body */
    }
    // 502/503/504 from the dev proxy mean the API never answered at all.
    if (response.status >= 502 && response.status <= 504) throw new ApiOfflineError(detail)
    throw new Error(detail)
  }

  return response
}

async function request(path, options = {}) {
  const response = await send(path, options)
  if (response.status === 204) return null
  return response.json()
}

/**
 * A page of rows plus how many there are in total.
 *
 * The count rides on a header rather than wrapping the body, so the endpoints
 * keep returning plain lists and every other caller is unaffected.
 */
async function requestPage(path) {
  const response = await send(path)
  const total = Number(response.headers.get('X-Total-Count'))
  const items = await response.json()
  return { items, total: Number.isFinite(total) ? total : items.length }
}

const get = (path) => request(path)
const post = (path, body) => request(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const patch = (path, body) => request(path, { method: 'PATCH', body: JSON.stringify(body) })
const del = (path) => request(path, { method: 'DELETE' })

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) value.forEach((item) => search.append(key, item))
    else search.append(key, value)
  })
  const string = search.toString()
  return string ? `?${string}` : ''
}

export const api = {
  stats: () => get('/stats'),
  health: () => get('/health'),

  opportunities: (filters) => requestPage(`/opportunities${query(filters)}`),
  opportunity: (id) => get(`/opportunities/${id}`),
  updateOpportunity: (id, body) => patch(`/opportunities/${id}`, body),
  deleteOpportunity: (id) => del(`/opportunities/${id}`),

  resumeAdvice: (id) => get(`/opportunities/${id}/resume-advice`),
  generateResumeAdvice: (id, refresh = false) =>
    post(`/opportunities/${id}/resume-advice${query({ refresh })}`),
  deleteResumeAdvice: (id) => del(`/opportunities/${id}/resume-advice`),

  roleAnalysis: () => get('/insights/roles'),
  generateRoleAnalysis: (body) => post('/insights/roles', body || {}),
  updateRoleAnalysis: (id, body) => patch(`/insights/roles/${id}`, body),
  roleAnalysisHistory: () => get('/insights/roles/history'),

  applications: (filters) => get(`/applications${query(filters)}`),
  createApplication: (body) => post('/applications', body),
  updateApplication: (id, body) => patch(`/applications/${id}`, body),
  deleteApplication: (id) => del(`/applications/${id}`),

  sources: (filters) => requestPage(`/sources${query(filters)}`),
  createSource: (body) => post('/sources', body),
  updateSource: (id, body) => patch(`/sources/${id}`, body),
  deleteSource: (id) => del(`/sources/${id}`),
  discoverSources: (body) => post('/sources/discover', body),
  proposals: (status = 'pending') => get(`/sources/proposals${query({ status })}`),
  approveProposal: (id) => post(`/sources/proposals/${id}/approve`),
  rejectProposal: (id) => post(`/sources/proposals/${id}/reject`),

  runScrape: () => post('/scrape/run-now'),
  scrapeSource: (id) => post(`/scrape/source/${id}`),
  scrapeStatus: () => get('/scrape/status'),
  scrapeLogTail: (limit = 120) => get(`/scrape/log-tail${query({ limit })}`),
  scrapeLogs: (filters) => get(`/scrape/logs${query(filters)}`),

  walten: () => get('/walten'),
  waltenSession: (id) => get(`/walten/sessions/${id}`),
  createWaltenSession: (body) => post('/walten/sessions', body),
  updateWaltenSession: (id, body) => patch(`/walten/sessions/${id}`, body),
  deleteWaltenSession: (id) => del(`/walten/sessions/${id}`),
  sendWaltenMessage: (id, prompt) => post(`/walten/sessions/${id}/messages`, { prompt }),
  approveWalten: (id) => post(`/walten/sessions/${id}/approve`),
  rejectWalten: (id) => post(`/walten/sessions/${id}/reject`),
  stopWalten: (id) => post(`/walten/sessions/${id}/stop`),
  waltenUndoPreview: (id, messageId) => get(`/walten/sessions/${id}/messages/${messageId}/undo`),
  undoWaltenMessage: (id, messageId) => post(`/walten/sessions/${id}/messages/${messageId}/undo`),
  uploadWaltenContext: (id, file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`/walten/sessions/${id}/context`, { method: 'POST', body: form })
  },

  resumes: () => get('/resumes'),
  resumeInstance: (id) => get(`/resumes/${id}`),
  createResumeInstance: (body) => post('/resumes', body || {}),
  updateResumeInstance: (id, body) => patch(`/resumes/${id}`, body),
  deleteResumeInstance: (id) => del(`/resumes/${id}`),
  compileResumeInstance: (id) => post(`/resumes/${id}/compile`),
  fixResumeInstance: (id, ids) => post(`/resumes/${id}/fix`, ids ? { ids } : {}),
  makeResumeDefault: (id) => post(`/resumes/${id}/default`),
  resumeLinks: (id) => get(`/resumes/${id}/linked`),

  resumeAssets: () => get('/resumes/assets'),
  uploadResumeAsset: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/resumes/assets', { method: 'POST', body: form })
  },
  deleteResumeAsset: (name) => del(`/resumes/assets/${encodeURIComponent(name)}`),
  // Not a JSON call: pdf.js fetches this for the preview, and the download
  // link points a browser straight at it. `v` changes after every render so a
  // cached copy is never shown in place of the document just compiled.
  resumePdfUrl: (id, { download = false, version = '' } = {}) =>
    `${BASE}/resumes/${id}/pdf${query({ download: download || undefined, v: version || undefined })}`,

  // Straight to an <img>, so a URL rather than a fetch. Unknown or untracked
  // domains 404 and the caller falls back to a generic glyph.
  faviconUrl: (domain) => `${BASE}/favicons/${encodeURIComponent(domain)}`,

  settings: () => get('/settings'),
  checkClaudePath: (path) => post('/settings/claude-path', { path }),
  updateSettings: (body) => patch('/settings', body),
  resume: () => get('/settings/resume'),
  resumeTex: () => get('/settings/resume-tex'),
  saveResumeTex: (latex) => request('/settings/resume-tex', { method: 'PUT', body: JSON.stringify({ latex }) }),
  fixResumeTex: (ids) => post('/settings/resume-tex/fix', ids ? { ids } : {}),
  latexStatus: () => get('/settings/latex'),
  checkLatexPath: (path) => post('/settings/latex-path', { path }),
  uploadResume: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/settings/resume', { method: 'POST', body: form })
  },
}

/**
 * Stored values stay `assistant` / `engineer` (the database CHECK constraint and
 * the agent's permission policy key off them); only the display names changed.
 */
export const WALTEN_MODES = [
  {
    value: 'assistant',
    label: 'Assist',
    summary: 'Works on your data',
    description: 'Query and tidy the database, re-tag and re-score listings, find sources, run the scraper, write reports. Cannot change the app itself.',
  },
  {
    value: 'engineer',
    label: 'Build',
    summary: 'Can change the app',
    description: 'Everything Assist does, plus editing source, config and build tooling. Commits to git before each change so you can revert.',
  },
]

export const WALTEN_MODELS = [
  {
    value: 'opus',
    label: 'Opus 5',
    description: 'Most capable. Multi-step refactors and analysis that needs care.',
  },
  {
    value: 'sonnet',
    label: 'Sonnet 5',
    description: 'Balanced speed and depth. The right default for most tasks.',
  },
  {
    value: 'haiku',
    label: 'Haiku 4.5',
    description: 'Fastest and cheapest. Lookups, counts and small tidy-ups.',
  },
]

export const WALTEN_PRESETS = [
  { label: 'Find duplicates', prompt: 'Find listings that are duplicates of each other (same role at the same organisation under different URLs). List them with ids; do not change anything yet.' },
  { label: 'Audit junk listings', prompt: 'Find rows in opportunities that are not really job listings (news articles, help pages, upload forms). List them with ids and scores, and say which you would delete.' },
  { label: 'Suggest new sources', prompt: 'Look at the sources I already track and my resume, then search the web for three to five listing pages I am missing. Explain why each fits before adding anything.' },
]

export const REQUIREMENT_STATUSES = ['met', 'partial', 'gap', 'unknown']

export const OPPORTUNITY_TYPES = ['internship', 'job', 'research', 'grad_program', 'fellowship', 'other']
export const EXPERIENCE_LEVELS = ['student', 'entry', 'mid', 'senior', 'postdoc', 'any']
export const SOURCE_TYPES = [
  'job_board',
  'company_careers',
  'research_program',
  'aggregator',
  'university',
  'government',
]
export const APPLICATION_STATUSES = [
  'bookmarked',
  'planning_to_apply',
  'applied',
  'assessment',
  'interview',
  'offer',
  'rejected',
  'withdrawn',
  'closed',
]
