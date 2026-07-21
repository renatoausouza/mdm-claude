import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { setApiLanguage } from '../api/client'
import { FALLBACK_LANGUAGE, LANGUAGE_STORAGE_KEY, SUPPORTED_LANGUAGES, translations, type Lang } from './translations'

interface LanguageContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: string, vars?: Record<string, string | number>) => string
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

function detectDefaultLanguage(): Lang {
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (stored && (SUPPORTED_LANGUAGES as string[]).includes(stored)) return stored as Lang
  // Browser-detected, Portuguese-first fallback (see solution-brief.md-style
  // reasoning: this is a Brazilian business tool) — anything other than an
  // explicit "en"-family locale defaults to Portuguese.
  return navigator.language.toLowerCase().startsWith('en') ? 'en' : FALLBACK_LANGUAGE
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in vars ? String(vars[name]) : match))
}

// Set synchronously at module load, before React starts rendering — same
// reasoning as AuthContext's equivalent call: on a hard reload, a child
// component's own data-fetch effect can fire before this provider's
// useEffect below (child effects run before parent effects), which would
// otherwise send that first request with no language header.
setApiLanguage(detectDefaultLanguage())

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectDefaultLanguage)

  // The API client's language header is a module-level value (mirrors
  // setAuthToken's pattern in AuthContext) so every fetch — including ones
  // fired before this component re-renders — carries the current choice.
  useEffect(() => {
    setApiLanguage(lang)
    document.title = translations[lang]['layout.pageTitle']
  }, [lang])

  function setLang(next: Lang): void {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, next)
    setLangState(next)
  }

  function t(key: string, vars?: Record<string, string | number>): string {
    const template = translations[lang][key] ?? translations.en[key] ?? key
    return interpolate(template, vars)
  }

  return <LanguageContext.Provider value={{ lang, setLang, t }}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage must be used within a LanguageProvider')
  return ctx
}
