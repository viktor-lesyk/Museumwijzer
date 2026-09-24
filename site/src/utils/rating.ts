import ratingsData from '../../../data/enrichment/ratings.json';

export interface RatingRecord {
  slug: string;
  name: string;
  rating: number | null;
  reviews_count: number;
  source: string;
}

const ratingsMap: Record<string, RatingRecord> = {};
for (const r of (ratingsData.museums || [])) {
  if (r.slug) {
    ratingsMap[r.slug] = r as RatingRecord;
  }
}

export function getMuseumRating(slug: string, duplicateOf?: string): RatingRecord | undefined {
  return ratingsMap[slug] || (duplicateOf ? ratingsMap[duplicateOf] : undefined);
}

export function formatReviewsCount(count: number, lang: string): string {
  if (!count) return '';
  if (count >= 1000000) {
    const m = (count / 1000000).toFixed(1).replace('.0', '');
    if (lang === 'uk') return `${m} млн`;
    return `${m}M`;
  }
  if (count >= 1000) {
    const k = (count / 1000).toFixed(count >= 10000 ? 0 : 1).replace('.0', '');
    if (lang === 'uk') return `${k} тис.`;
    return `${k}k`;
  }
  return String(count);
}
