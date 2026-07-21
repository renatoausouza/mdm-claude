import { useLanguage } from '../i18n/LanguageContext'
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
  const { t } = useLanguage()

  if (!field) {
    return (
      <div className="field-display field-display-missing">
        <div className="field-label">
          {label}
          {required && <span className="field-required"> *</span>}
        </div>
        <div className="field-value field-value-empty">{t('fieldDisplay.notExtracted')}</div>
      </div>
    )
  }

  const lowConfidence = field.confidence < LOW_CONFIDENCE_DISPLAY_THRESHOLD
  // extraction_schema.ts's Provenance.source is a known set ('regex' |
  // 'llm' | 'pdf_layout') plus an escape hatch (plain `string`) for any
  // future source the frontend doesn't know about yet — t() falls back to
  // returning the raw key when a translation is missing, so detect that
  // and fall back to the untranslated source value itself instead of
  // showing a raw dotted key on screen.
  const sourceKey = `fieldDisplay.source.${field.provenance.source}`
  const translatedSource = t(sourceKey)
  const sourceLabel = translatedSource === sourceKey ? field.provenance.source : translatedSource

  return (
    <div className={`field-display ${lowConfidence ? 'field-display-low-confidence' : ''}`}>
      <div className="field-label">
        {label}
        {required && <span className="field-required"> *</span>}
      </div>
      <div className="field-value">{field.value}</div>
      <div className="field-meta">
        <span className={`confidence-badge ${lowConfidence ? 'confidence-low' : 'confidence-high'}`}>
          {t('fieldDisplay.confidence', { percent: Math.round(field.confidence * 100) })}
        </span>
        <span
          className="provenance-badge"
          title={field.provenance.page ? t('fieldDisplay.page', { page: field.provenance.page }) : undefined}
        >
          {field.provenance.page != null
            ? t('fieldDisplay.sourceWithPage', { source: sourceLabel, page: field.provenance.page })
            : t('fieldDisplay.source', { source: sourceLabel })}
        </span>
      </div>
    </div>
  )
}
