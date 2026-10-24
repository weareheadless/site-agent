'use client';

import type { ReactNode } from 'react';
import { useHelloAdaTranslations } from '../api/useHelloAdaTranslations';
import { formatRichTextReview, getReviewChanges, getReviewTarget, isRichTextReview, type GrowthReview } from '../lib/growth-review';

function renderValue(value: unknown, t: (key: string) => string): ReactNode {
  if (value === null) return <span>{t('growth.clarityEmpty')}</span>;
  if (value === undefined) return <span>{t('growth.clarityRemoved')}</span>;
  if (typeof value === 'string') return value.trim() ? value : <span>{t('growth.clarityEmpty')}</span>;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  const prose = formatRichTextReview(value, {
    underlined: t('growth.clarityUnderlined'),
    linkDestination: t('growth.clarityLinkDestination'),
    opensInNewTab: t('growth.clarityOpensNewTab'),
  });
  if (prose !== null) return <>
    <div>{prose.trim() || <span>{t('growth.clarityEmpty')}</span>}</div>
    {isRichTextReview(value) ? <details className="helloada-growth-change-review__richtext-details">
      <summary>{t('growth.clarityRichTextDetails')}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details> : null}
  </>;
  if (Array.isArray(value)) {
    return value.length ? <ul>{value.map((item, index) => <li key={index}>{renderValue(item, t)}</li>)}</ul> : <span>{t('growth.clarityEmpty')}</span>;
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    return entries.length ? <dl className="helloada-growth-change-review__object">{entries.map(([key, item]) => (
      <div key={key}><dt>{key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ')}</dt><dd>{renderValue(item, t)}</dd></div>
    ))}</dl> : <span>{t('growth.clarityEmpty')}</span>;
  }
  return String(value);
}

export function GrowthChangeReview({ review }: { review?: GrowthReview | null }) {
  const { t } = useHelloAdaTranslations();
  const changes = getReviewChanges(review);
  const target = getReviewTarget(review);
  if (!changes.length) return null;

  return <section className="helloada-growth-change-review" aria-label={t('growth.clarityProposed')}>
    {target ? <div className="helloada-growth-change-review__target">
      <strong>{target.title}</strong>
      {target.path ? <code>{target.path}</code> : null}
    </div> : null}
    <div className="helloada-growth-change-review__changes">
      {changes.map((change, index) => <article className="helloada-growth-change-review__change" key={`${change.path}:${index}`}>
        <h4 className="helloada-growth-change-review__field">{change.labelKey ? t(change.labelKey) : change.label}</h4>
        <div className="helloada-growth-change-review__comparison">
          <div className="helloada-growth-change-review__side">
            <h5>{t('growth.clarityCurrently')}</h5>
            <div className="helloada-growth-change-review__value">{change.kind === 'added' ? <span>{t('growth.clarityNotPresent')}</span> : renderValue(change.before, t)}</div>
          </div>
          <div className="helloada-growth-change-review__side">
            <h5>{t('growth.clarityProposed')}</h5>
            <div className="helloada-growth-change-review__value">{change.kind === 'removed' ? <span>{t('growth.clarityRemoved')}</span> : renderValue(change.after, t)}</div>
          </div>
        </div>
      </article>)}
    </div>
  </section>;
}
