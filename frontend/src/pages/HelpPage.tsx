import { useLanguage } from '../i18n/LanguageContext'

export function HelpPage() {
  const { t } = useLanguage()

  return (
    <div className="help-page">
      <h1>{t('help.title')}</h1>
      <p className="field-hint">{t('help.intro')}</p>

      <section className="help-section">
        <h2>{t('help.uploadTitle')}</h2>
        <p>{t('help.uploadBody')}</p>
      </section>

      <section className="help-section">
        <h2>{t('help.reviewTitle')}</h2>
        <p>{t('help.reviewBody')}</p>
      </section>

      <section className="help-section">
        <h2>{t('help.decisionTitle')}</h2>
        <p>{t('help.decisionBody')}</p>
      </section>

      <section className="help-section">
        <h2>{t('help.segregationTitle')}</h2>
        <p>{t('help.segregationBody')}</p>
      </section>

      <section className="help-section">
        <h2>{t('help.duplicatesTitle')}</h2>
        <p>{t('help.duplicatesBody')}</p>
      </section>

      <section className="help-section">
        <h2>{t('help.auditTitle')}</h2>
        <p>{t('help.auditBody')}</p>
      </section>

      <section className="help-section">
        <h2>{t('help.languageTitle')}</h2>
        <p>{t('help.languageBody')}</p>
      </section>
    </div>
  )
}
