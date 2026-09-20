export const languages = {
  nl: {
    code: 'nl',
    name: 'Nederlands',
    dir: 'ltr',
    ticketLang: 'NL',
  },
  en: {
    code: 'en',
    name: 'English',
    dir: 'ltr',
    ticketLang: 'EN',
  },
  uk: {
    code: 'uk',
    name: 'Українська',
    dir: 'ltr',
    ticketLang: 'UK',
  },
} as const;

export type Locale = keyof typeof languages;
export const defaultLocale: Locale = 'nl';
