import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { strings, type Lang } from './strings'

type Ctx = { lang: Lang; setLang: (l: Lang) => void; toggle: () => void; t: (key: string) => string }

const LanguageContext = createContext<Ctx>({ lang: 'ko', setLang: () => {}, toggle: () => {}, t: (k) => k })

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => ((localStorage.getItem('medilaw_lang') as Lang) || 'ko'))
  const setLang = (l: Lang) => {
    setLangState(l)
    localStorage.setItem('medilaw_lang', l)
    document.documentElement.lang = l
  }
  const toggle = () => setLang(lang === 'ko' ? 'en' : 'ko')
  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])
  const t = (key: string) => strings[lang][key] ?? strings.ko[key] ?? key
  return <LanguageContext.Provider value={{ lang, setLang, toggle, t }}>{children}</LanguageContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useLang = () => useContext(LanguageContext)
