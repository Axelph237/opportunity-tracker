import { useCallback, useEffect, useRef, useState } from 'react'
import { PlusIcon, TrashIcon } from './icons'
import Tooltip from './Tooltip'
import { api } from '../api'

const IMAGE_SUFFIXES = ['.png', '.jpg', '.jpeg', '.gif', '.webp']

const isImage = (name) => IMAGE_SUFFIXES.some((suffix) => name.toLowerCase().endsWith(suffix))

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/**
 * What to write into the source when an asset is clicked.
 *
 * An image is almost always an `\includegraphics`, and anything else is a file
 * the document pulls in — guessing right saves the user looking up the syntax,
 * and guessing wrong costs them one undo.
 */
function insertionFor(name) {
  if (isImage(name)) return `\\includegraphics[width=1in]{${name}}`
  if (name.endsWith('.tex')) return `\\input{${name.replace(/\.tex$/, '')}}`
  if (name.endsWith('.sty')) return `\\usepackage{${name.replace(/\.sty$/, '')}}`
  if (name.endsWith('.bib')) return `\\bibliography{${name.replace(/\.bib$/, '')}}`
  return name
}

/**
 * Files every resume version compiles against.
 *
 * Shared across versions rather than owned by one: a university seal or a
 * headshot belongs to the person, and making each tailored copy carry its own
 * would mean re-uploading the same logo for every application.
 */
export default function ResumeAssets({ onInsert, onChanged }) {
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const fileInput = useRef(null)

  const load = useCallback(async () => {
    try {
      setAssets(await api.resumeAssets())
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const upload = async (files) => {
    if (!files?.length) return
    setBusy(true)
    setError(null)
    const failures = []
    try {
      // Sequential rather than Promise.all: the failure message needs to name
      // the file that was rejected, and a rejected .zip should not take the
      // valid images dropped alongside it down with it.
      for (const file of files) {
        try {
          await api.uploadResumeAsset(file)
        } catch (err) {
          failures.push(`${file.name}: ${err.message}`)
        }
      }
      await load()
      // After the refresh, not before: `load` clears the error on success, so
      // reporting a rejected file first would wipe the message that explains
      // why it is missing from the list.
      if (failures.length) setError(failures.join(' · '))
      onChanged?.()
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const remove = async (name) => {
    setBusy(true)
    try {
      await api.deleteResumeAsset(name)
      await load()
      onChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault()
        upload([...(event.dataTransfer?.files || [])])
      }}
    >
      <div className="flex items-center justify-between gap-2 border-b border-outline-variant px-3 py-2">
        <Tooltip label="Files every version compiles against. Click one to insert it at the cursor.">
          <span className="label-data cursor-help">Assets</span>
        </Tooltip>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.eps,.tex,.sty,.cls,.bib,.bst"
          className="hidden"
          id="resume-asset-upload"
          onChange={(event) => upload([...(event.target.files || [])])}
        />
        <label htmlFor="resume-asset-upload" className="btn cursor-pointer" aria-disabled={busy}>
          <PlusIcon />
          Add
        </label>
      </div>

      {error ? <p className="px-3 py-2 text-error">{error}</p> : null}

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {assets.map((asset) => (
          <li
            key={asset.name}
            className="group flex items-center gap-2 border-b border-outline-variant/60 px-3 py-1.5"
          >
            {/* A `title` rather than the app's Tooltip: the list scrolls, and a
                scroll container clips on both axes, so an absolutely
                positioned bubble inside it is cut off at the panel edge. The
                browser draws this one outside the clip. */}
            <button
              type="button"
              aria-label={`Insert ${asset.name}`}
              title={`Insert ${insertionFor(asset.name)} at the cursor`}
              onClick={() => onInsert?.(insertionFor(asset.name))}
              className="min-w-0 flex-1 text-left transition-colors hover:text-primary"
            >
              <span className="line-clamp-1 font-mono text-data text-on-surface">{asset.name}</span>
              <span className="font-mono text-data text-on-surface-variant">
                {formatSize(asset.size)}
              </span>
            </button>
            <button
              type="button"
              aria-label={`Delete ${asset.name}`}
              title="Delete this asset"
              disabled={busy}
              onClick={() => remove(asset.name)}
              className="shrink-0 text-on-surface-variant opacity-0 transition-opacity hover:text-error focus:opacity-100 group-hover:opacity-100 disabled:opacity-40"
            >
              <TrashIcon className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
      </ul>

      {!loading && !assets.length ? (
        <p className="px-3 py-3 text-on-surface-variant">
          No assets. Add a logo or a photo your resume includes — or drop files here. They are
          copied in beside the source every time it renders.
        </p>
      ) : null}
    </div>
  )
}
