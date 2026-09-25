import type { Locale } from '../i18n/languages';

export interface PriceRecord {
  status: 'paid' | 'free' | 'closed' | 'blocked_by_bot_protection' | 'unknown' | string;
  primary_adult_eur: number | null;
  door_adult_eur: number | null;
  online_adult_eur: number | null;
  variants: Record<string, number> | null;
  cheapest_adult_eur: number | null;
  price_note: string | null;
  free_for: string[];
  quote: string | null;
  source_url: string | null;
  page_title: string;
  reasoning_summary: string;
  checked_on: string;
  mode: string;
  extractor_model: string;
  verifier_model: string;
  confidence: 'high' | 'medium' | 'low' | string;
}

export function formatPriceNumber(val: number | null | undefined, lang: Locale = 'nl'): string {
  if (val === null || val === undefined || isNaN(val)) return '';
  const isInt = Number.isInteger(val) || val % 1 === 0;
  if (isInt) {
    return String(Math.round(val));
  }
  const fixed = val.toFixed(2);
  return lang === 'en' ? fixed : fixed.replace('.', ',');
}

export function formatCheckedDate(dateStr: string | null | undefined, lang: Locale = 'nl'): string {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    const dateLocales: Record<Locale, string> = {
      nl: 'nl-NL',
      en: 'en-GB',
      uk: 'uk-UA',
    };
    return d.toLocaleDateString(dateLocales[lang] || 'nl-NL', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

export function formatVariantLabel(key: string, lang: Locale = 'nl'): string {
  const labels: Record<string, Record<Locale, string>> = {
    weekend_holiday: {
      nl: 'Weekend & vakanties',
      en: 'Weekends & holidays',
      uk: 'Вихідні та свята',
    },
    plusticket_tower_climb: {
      nl: 'Plusticket (incl. torenbeklimming)',
      en: 'Plus ticket (incl. tower climb)',
      uk: 'Плюс-квиток (з підйомом на вежу)',
    },
    familiepas: {
      nl: 'Familiepas',
      en: 'Family pass',
      uk: 'Сімейний квиток',
    },
    familiepas_2_adults_2_children: {
      nl: 'Familiepas (2 volwassenen + 2 kinderen)',
      en: 'Family pass (2 adults + 2 children)',
      uk: 'Сімейний квиток (2 дорослих + 2 дітей)',
    },
    meedoen_pas: {
      nl: 'MeedoenPas',
      en: 'Participation Pass',
      uk: 'Картка MeedoenPas',
    },
    cjp_pas: {
      nl: 'CJP-pas',
      en: 'CJP pass',
      uk: 'Картка CJP',
    },
    rondleiding_gids: {
      nl: 'Met rondleiding',
      en: 'With guided tour',
      uk: 'З екскурсоводом',
    },
    chez_matisse_exhibition_surcharge: {
      nl: 'Tentoonstellingsticket (Chez Matisse)',
      en: 'Exhibition ticket (Chez Matisse)',
      uk: 'Виставковий квиток (Chez Matisse)',
    },
  };
  if (labels[key] && labels[key][lang]) {
    return labels[key][lang];
  }
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function getReportWrongPriceUrl(
  museumName: string,
  museumSlug: string,
  sourceUrl: string | null,
  lang: Locale = 'nl'
): string {
  const subjects: Record<Locale, string> = {
    nl: `Prijsmelding: ${museumName}`,
    en: `Price correction: ${museumName}`,
    uk: `Повідомлення про ціну: ${museumName}`,
  };
  const bodyText = `Museum: ${museumName} (${museumSlug})\nBronpagina / Source: ${sourceUrl || 'onbekend'}\n\nJuiste prijs / Correct price:\nToelichting / Details:\n`;
  return `mailto:museumwijzer@vlesyk.com?subject=${encodeURIComponent(subjects[lang] || subjects.nl)}&body=${encodeURIComponent(bodyText)}`;
}

