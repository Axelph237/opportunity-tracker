import {
  CONFIRM_KINDS,
  clearAllSuppressedConfirms,
  clearSuppressedConfirm,
  useSuppressedConfirms,
} from '../../components/ConfirmDialog'

export default function Confirmations() {
  const suppressed = useSuppressedConfirms()

  if (!suppressed.length) {
    return (
      <p className="text-on-surface-variant">
        Everything asks first. Tick <span className="text-on-surface">Do not ask again</span> in a
        confirmation to skip it; it will be listed here so you can turn it back on.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-outline-variant rounded border border-outline-variant bg-surface-container">
        {suppressed.map((key) => (
          <li key={key} className="flex items-center justify-between gap-4 px-4 py-3">
            <span>
              <span className="text-on-surface">{CONFIRM_KINDS[key] || key}</span>
              <span className="mt-1 block font-mono text-data text-on-surface-variant">
                no longer asks
              </span>
            </span>
            <button type="button" className="btn shrink-0" onClick={() => clearSuppressedConfirm(key)}>
              Ask again
            </button>
          </li>
        ))}
      </ul>
      {suppressed.length > 1 ? (
        <button type="button" className="btn" onClick={clearAllSuppressedConfirms}>
          Ask again for all
        </button>
      ) : null}
    </div>
  )
}
