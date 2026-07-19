export function ProgressBar({ label }: { label?: string }) {
  return (
    <div className="progress-bar" role="status" aria-live="polite">
      <div className="progress-bar-track">
        <div className="progress-bar-indeterminate" />
      </div>
      {label && <p className="progress-bar-label">{label}</p>}
    </div>
  )
}
