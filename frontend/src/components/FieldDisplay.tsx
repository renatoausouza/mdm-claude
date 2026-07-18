import type { FieldValue } from '../types/api'

// Below this, a field is flagged as low-confidence in the UI too — purely
// a display cue; the backend's actual confidence-gate threshold
// (MDM_CONFIDENCE_THRESHOLD) is what forces review server-side.
const LOW_CONFIDENCE_DISPLAY_THRESHOLD = 0.7

interface FieldDisplayProps {
  label: string
  field: FieldValue | null | undefined
  required?: boolean
}

// Renders a single extracted field with its confidence and provenance
// highlighted (D16) — React escapes all text content by default, so this
// is also where FR-18's "output-encoded wherever rendered" requirement for
// untrusted extracted values is satisfied: `field.value` below is never
// injected as raw HTML anywhere in this app.
export function FieldDisplay({ label, field, required }: FieldDisplayProps) {
  if (!field) {
    return (
      <div className="field-display field-display-missing">
        <div className="field-label">
          {label}
          {required && <span className="field-required"> *</span>}
        </div>
        <div className="field-value field-value-empty">Not extracted</div>
      </div>
    )
  }

  const lowConfidence = field.confidence < LOW_CONFIDENCE_DISPLAY_THRESHOLD

  return (
    <div className={`field-display ${lowConfidence ? 'field-display-low-confidence' : ''}`}>
      <div className="field-label">
        {label}
        {required && <span className="field-required"> *</span>}
      </div>
      <div className="field-value">{field.value}</div>
      <div className="field-meta">
        <span className={`confidence-badge ${lowConfidence ? 'confidence-low' : 'confidence-high'}`}>
          {Math.round(field.confidence * 100)}% confidence
        </span>
        <span className="provenance-badge" title={field.provenance.page ? `Page ${field.provenance.page}` : undefined}>
          source: {field.provenance.source}
          {field.provenance.page != null ? `, p.${field.provenance.page}` : ''}
        </span>
      </div>
    </div>
  )
}
