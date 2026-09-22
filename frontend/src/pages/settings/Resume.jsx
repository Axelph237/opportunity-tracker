import { useRef } from 'react'
import { api } from '../../api'
import { formatDateTime } from '../../format'

export default function Resume({ resume, act }) {
  const fileInput = useRef(null)

  const upload = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    await act(() => api.uploadResume(file), `Loaded ${file.name}.`)
    if (fileInput.current) fileInput.current.value = ''
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-6 rounded border border-outline-variant bg-surface-container p-4">
        <div>
          <div className="label-data">File</div>
          <div className="mt-1 font-mono text-on-surface">{resume?.filename || 'none loaded'}</div>
        </div>
        <div>
          <div className="label-data">Extracted</div>
          <div className="mt-1 font-mono text-on-surface">
            {resume?.characters ? `${resume.characters.toLocaleString()} chars` : '—'}
          </div>
        </div>
        <div>
          <div className="label-data">Updated</div>
          <div className="mt-1 font-mono text-on-surface">{formatDateTime(resume?.updated_at)}</div>
        </div>
        <div className="ml-auto">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.txt,.md"
            onChange={upload}
            className="hidden"
            id="resume-upload"
          />
          <label htmlFor="resume-upload" className="btn btn-primary cursor-pointer">
            Upload
          </label>
        </div>
      </div>

      <p className="text-on-surface-variant">PDF text is extracted with pypdf and cached.</p>

      {!resume?.loaded ? (
        <p className="text-tertiary">No resume loaded — scores will be generic.</p>
      ) : null}
    </div>
  )
}
