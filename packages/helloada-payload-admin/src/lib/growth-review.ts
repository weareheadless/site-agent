export type GrowthReview = {
  before?: unknown;
  after?: unknown;
  changes?: Record<string, unknown>;
  route?: string | null;
  article?: unknown;
  changeOperations?: { path: string; find: string; replace: string }[];
};

export type GrowthReviewChange = {
  path: string;
  label: string;
  before: unknown;
  after: unknown;
  kind: 'added' | 'removed' | 'changed';
  labelKey?: string;
};

const own = (value: object, key: string) => Object.prototype.hasOwnProperty.call(value, key);
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const same = (a: unknown, b: unknown): boolean => {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((item, i) => same(item, b[i]));
  if (isRecord(a) && isRecord(b)) {
    const ak = Object.keys(a); const bk = Object.keys(b);
    return ak.length === bk.length && ak.every(key => own(b, key) && same(a[key], b[key]));
  }
  return false;
};

const friendlyNames: Record<string, string> = {
  image: 'Image', alt: 'Image description', url: 'Image URL', filename: 'Image file', meta: 'Search settings',
  metaTitle: 'Search title', metaDescription: 'Search description', title: 'Title', name: 'Name', slug: 'Page address',
  path: 'Page address', description: 'Description', excerpt: 'Article summary', summary: 'Summary', body: 'Article text',
  content: 'Content', author: 'Author', featuredImage: 'Featured image', caption: 'Caption', keyword: 'Search phrase',
  primaryKeyword: 'Main search phrase', root: 'Article text', children: 'Text', text: 'Text', value: 'Value', type: 'Type',
  format: 'Format', width: 'Width', height: 'Height', id: 'ID', direction: 'Text direction', indent: 'Indent',
  version: 'Version', detail: 'Detail', mode: 'Mode', style: 'Style', tag: 'Heading level', listType: 'List type',
  fields: 'Link settings', newTab: 'Open in new tab', url2: 'Link address',
};

const fieldTranslation: Record<string, string> = {
  'seo.metaDescription': 'growth.clarityFieldSearchDescription', 'seo.description': 'growth.clarityFieldSearchDescription',
  metaDescription: 'growth.clarityFieldSearchDescription', 'seo.title': 'growth.clarityFieldSearchTitle', metaTitle: 'growth.clarityFieldSearchTitle',
  excerpt: 'growth.clarityFieldArticleSummary', summary: 'growth.clarityFieldArticleSummary', body: 'growth.clarityFieldArticleText',
  content: 'growth.clarityFieldContent', title: 'growth.clarityFieldTitle', author: 'growth.clarityFieldAuthor',
  featuredImage: 'growth.clarityFieldFeaturedImage', 'seo.image.alt': 'growth.clarityFieldImageDescription',
  image: 'growth.clarityFieldImage', alt: 'growth.clarityFieldImageDescription', url: 'growth.clarityFieldImageUrl',
  filename: 'growth.clarityFieldImageFile', slug: 'growth.clarityFieldPageAddress', path: 'growth.clarityFieldPageAddress',
  description: 'growth.clarityFieldDescription', name: 'growth.clarityFieldName', caption: 'growth.clarityFieldCaption',
  keyword: 'growth.clarityFieldSearchPhrase', primaryKeyword: 'growth.clarityFieldSearchPhrase',
  width: 'growth.clarityFieldWidth', height: 'growth.clarityFieldHeight',
};

export function isRichTextReview(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const root = isRecord(value.root) ? value.root : value;
  return root.type === 'root' && Array.isArray(root.children);
}

function labelForPath(path: string): string {
  const normalized = path.replace(/\[(\d+)\]/g, '.$1').split('.');
  if (normalized[0] === 'body' || normalized[0] === 'content') return 'Article text';
  if (normalized[0] === 'seo' && ['metaDescription', 'description'].includes(normalized[1])) return 'Search description';
  if (normalized[0] === 'seo' && normalized[1] === 'title') return 'Search title';
  if (normalized[0] === 'seo' && normalized[1] === 'image' && normalized[2] === 'alt') return 'Image description';
  return path.split('.').map(segment => {
    const arrayPart = segment.match(/^(.*)\[(\d+)\]$/);
    const key = arrayPart?.[1] || segment;
    if (key === 'seo' || key === 'root' || key === 'children') return '';
    const named = friendlyNames[key] || key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ');
    return arrayPart ? `${named} ${Number(arrayPart[2]) + 1}` : named;
  }).filter(Boolean).join(' · ');
}

function labelKeyForPath(path: string): string | undefined {
  const normalized = path.replace(/\[(\d+)\]/g, '.$1').split('.');
  if (normalized[0] === 'body') return 'growth.clarityFieldArticleText';
  if (normalized[0] === 'seo' && normalized[1] === 'metaDescription') return 'growth.clarityFieldSearchDescription';
  if (normalized[0] === 'seo' && normalized[1] === 'title') return 'growth.clarityFieldSearchTitle';
  return fieldTranslation[path] || fieldTranslation[normalized.at(-1) || ''] || fieldTranslation[normalized[0]];
}

function collectDiff(before: unknown, after: unknown, path: string, output: GrowthReviewChange[], hasBefore: boolean, hasAfter: boolean) {
  if (hasBefore && hasAfter && same(before, after)) return;
  if (isRichTextReview(before) || isRichTextReview(after)) {
    output.push({ path, label: labelForPath(path), labelKey: labelKeyForPath(path), before: hasBefore ? before : undefined,
      after: hasAfter ? after : undefined, kind: !hasBefore ? 'added' : !hasAfter ? 'removed' : 'changed' });
    return;
  }
  // Treat null as a real value so that removals and explicit clears remain visible.
  if (isRecord(before) && isRecord(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
    for (const key of keys) collectDiff(before[key], after[key], path ? `${path}.${key}` : key, output, own(before, key), own(after, key));
    return;
  }
  if (Array.isArray(before) && Array.isArray(after)) {
    const length = Math.max(before.length, after.length);
    for (let i = 0; i < length; i++) collectDiff(before[i], after[i], `${path}[${i}]`, output, i < before.length, i < after.length);
    return;
  }
  output.push({ path, label: labelForPath(path), labelKey: labelKeyForPath(path), before: hasBefore ? before : undefined, after: hasAfter ? after : undefined,
    kind: !hasBefore ? 'added' : !hasAfter ? 'removed' : 'changed' });
}

function collectProposed(value: unknown, path: string, output: GrowthReviewChange[]) {
  if (isRichTextReview(value)) {
    output.push({ path, label: labelForPath(path), labelKey: labelKeyForPath(path), before: undefined, after: value, kind: 'changed' });
    return;
  }
  if (isRecord(value) && Object.keys(value).length) {
    for (const key of Object.keys(value).sort()) collectProposed(value[key], path ? `${path}.${key}` : key, output);
    return;
  }
  if (Array.isArray(value) && value.length) {
    value.forEach((item, index) => collectProposed(item, `${path}[${index}]`, output));
    return;
  }
  output.push({ path, label: labelForPath(path), labelKey: labelKeyForPath(path), before: undefined, after: value, kind: 'changed' });
}

export function getReviewChanges(review?: GrowthReview | null): GrowthReviewChange[] {
  if (!review) return [];
  const before = review.before;
  const after = review.after;
  if ((before !== undefined || after !== undefined) && !(before === null && after === null)) {
    const changes: GrowthReviewChange[] = [];
    collectDiff(before, after, '', changes, before !== undefined, after !== undefined);
    return changes;
  }
  // Legacy exact field map: preserve each supplied key and its value.
  const legacy: GrowthReviewChange[] = [];
  for (const [path, next] of Object.entries(review.changes || {}).sort(([a], [b]) => a.localeCompare(b))) collectProposed(next, path, legacy);
  for (const operation of review.changeOperations || []) legacy.push({ path: operation.path, label: labelForPath(operation.path), labelKey: labelKeyForPath(operation.path), before: operation.find, after: operation.replace, kind: 'changed' });
  legacy.sort((a, b) => a.path.localeCompare(b.path));
  return legacy;
}

/** Plain text rendering for changed Lexical values; destinations and marks stay visible without active links. */
export function formatRichTextReview(value: unknown, labels: { underlined?: string; linkDestination?: string; opensInNewTab?: string } = {}): string | null {
  if (!isRecord(value)) return null;
  if (value.root && isRecord(value.root)) return formatRichTextReview(value.root, labels);
  if (value.type === 'text' && typeof value.text === 'string') {
    const format = Number(value.format || 0);
    let text = value.text;
    if (format & 16) text = `\`${text}\``;
    if (format & 8) text = `[${text}] (${labels.underlined || 'underlined'})`;
    if (format & 4) text = `~~${text}~~`;
    if (format & 2) text = `*${text}*`;
    if (format & 1) text = `**${text}**`;
    return text;
  }
  if (value.type === 'linebreak') return '\n';
  if (!Array.isArray(value.children)) return null;
  const children = value.children.map(child => formatRichTextReview(child, labels) ?? '').join('');
  switch (value.type) {
    case 'paragraph': return `${children}\n\n`;
    case 'heading': return `${'#'.repeat(Math.max(1, Math.min(6, Number(String(value.tag || 'h2').replace('h', '')) || 2)))} ${children}\n\n`;
    case 'quote': return `> ${children}\n\n`;
    case 'listitem': return `• ${children}\n`;
    case 'link': {
      const fields = isRecord(value.fields) ? value.fields : {};
      const href = typeof fields.url === 'string' ? fields.url : '';
      const destination = href ? ` (${labels.linkDestination || 'link destination'}: ${href}${fields.newTab ? `; ${labels.opensInNewTab || 'opens in a new tab'}` : ''})` : '';
      return `${children}${destination}`;
    }
    default: return children;
  }
}

export type GrowthReviewTarget = { title: string; path: string | null };

function firstString(...values: unknown[]): string | undefined {
  return values.find((value): value is string => typeof value === 'string' && value.trim().length > 0)?.trim();
}

export function getReviewTarget(review?: GrowthReview | null): GrowthReviewTarget | null {
  if (!review) return null;
  const article = isRecord(review.article) ? review.article : {};
  const before = isRecord(review.before) ? review.before : {};
  const after = isRecord(review.after) ? review.after : {};
  const title = firstString(after.title, before.title, article.title);
  const path = firstString(review.route, after.path, after.slug, before.path, before.slug, article.path, article.slug);
  if (!title && !path) return null;
  return { title: title || path!, path: path || null };
}

export type DecisionTask = { title?: string; kind?: string; summary?: string; review?: GrowthReview | null };
export type DecisionPresentation = { heading: string; purpose: string | null; target: GrowthReviewTarget | null };

export function getDecisionPresentation(task: DecisionTask, t: (key: string) => string): DecisionPresentation {
  const changes = getReviewChanges(task.review);
  const target = getReviewTarget(task.review);
  const fields = new Set(changes.map(change => change.path.toLowerCase()));
  let headingKey: string | undefined;
  let purposeKey: string | undefined;
  if ([...fields].some(path => /(^|\.)metadescription$/.test(path) || /^seo\.description$/.test(path))) {
    headingKey = 'clarityHeadingSearchDescription'; purposeKey = 'clarityPurposeSearchDescription';
  } else if ([...fields].some(path => /(^|\.)(excerpt|summary)$/.test(path))) {
    headingKey = 'clarityHeadingArticleSummary'; purposeKey = 'clarityPurposeArticleSummary';
  } else if ([...fields].some(path => /(^|\.)(body|content)(\.|$)/.test(path))) {
    headingKey = 'clarityHeadingArticleText'; purposeKey = 'clarityPurposeArticleText';
  } else if ([...fields].some(path => /(^|\.)(title|metatitle)$/.test(path))) {
    headingKey = 'clarityHeadingTitle'; purposeKey = 'clarityPurposeTitle';
  }
  const authentic = firstString(task.title) || t('growth.clarityUntitledReview');
  return {
    heading: headingKey ? t(`growth.${headingKey}`) : authentic,
    purpose: purposeKey ? t(`growth.${purposeKey}`) : null,
    target,
  };
}
