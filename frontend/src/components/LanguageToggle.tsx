import { useLanguage } from '../i18n/LanguageContext'
import type { Lang } from '../i18n/translations'

const OPTIONS: { value: Lang; label: string }[] = [
  { value: 'pt', label: 'PT' },
  { value: 'en', label: 'EN' },
]

export function LanguageToggle({ className }: { className?: string }) {
  const { lang, setLang, t } = useLanguage()

  return (
    <div className={`language-toggle ${className ?? ''}`} role="group" aria-label={t('layout.languageToggleLabel')}>
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className={lang === option.value ? 'language-toggle-active' : ''}
          onClick={() => setLang(option.value)}
          aria-pressed={lang === option.value}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
