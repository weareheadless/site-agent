import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import test from 'node:test'
import ts from 'typescript'

// Execute the real import graph: source-text checks miss module-load crashes.
function load(url) {
  const source = readFileSync(url, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const sandbox = { exports: {}, require: name => load(new URL(`${name}.ts`, url)) }
  vm.runInNewContext(compiled, sandbox, { filename: url.pathname })
  return sandbox.exports
}

test('Growth translations load and contain the unified plan for every supported locale', () => {
  const { growthCopy } = load(new URL('../src/lib/growth-copy.ts', import.meta.url))
  assert.deepEqual(Object.keys(growthCopy).sort(), ['en', 'es', 'fr'])
  for (const language of ['en', 'es', 'fr']) {
    for (const key of ['growth.overview', 'growth.taskTitle', 'growth.task_needs_you', 'growth.growth_weekly',
      'growth.articleNotRunning', 'growth.articleResearchActive', 'growth.articleResearchComplete',
      'growth.articleResolvePrompt', 'growth.taskResolvePrompt', 'growth.taskState_not_running',
      'growth.panel_next', 'growth.panel_decisions', 'growth.panel_work', 'growth.panel_results', 'growth.homeTitle',
      'growth.decisionListTitle', 'growth.decisionCtaReview', 'growth.decisionCtaAnswer',
      'growth.ownerQuestionTitle', 'growth.ownerQuestionObserved', 'growth.ownerQuestionDetails',
      'growth.ownerQuestionHint', 'growth.ownerAnswerLabel',
      'growth.decisionCtaArticle', 'growth.decisionCtaChanges', 'growth.articleWhyThis',
      'growth.serviceNoticeTitle', 'growth.serviceNoticeBody', 'growth.openAdaWork',
      'growth.seeAllDecisions', 'growth.noDecisions', 'growth.noDecisionAskPrompt',
      'growth.resultsTitle', 'growth.resultsIntro', 'growth.attentionLabel', 'growth.nextScheduledLabel',
      'growth.growthProgressReadyForReview', 'growth.growthProgressServiceIssue',
      'growth.workSameIssueGroup', 'growth.workShowAffectedItems',
      'growth.growthOwnerReviewTask', 'growth.assessmentExecutionFailed', 'growth.assessmentExecutionBlocked',
      'growth.assessmentExecutionUncertain', 'growth.assessmentExecutionStale',
      'growth.articleResearchLocaleNeedsRepair', 'growth.articleResearchRequestNeedsRepair',
      'growth.assessmentNextRetry', 'growth.lastGrowthReview', 'growth.clarityCurrently', 'growth.clarityProposed',
      'growth.clarityRemoved', 'growth.clarityNotPresent', 'growth.clarityEmpty', 'growth.clarityNoChanges',
      'growth.clarityHeadingSearchDescription', 'growth.clarityPurposeSearchDescription',
      'growth.clarityHeadingArticleSummary', 'growth.clarityPurposeArticleSummary',
      'growth.clarityHeadingArticleText', 'growth.clarityPurposeArticleText',
      'growth.clarityHeadingTitle', 'growth.clarityPurposeTitle', 'growth.clarityUntitledReview',
      'growth.clarityEvidenceLabel', 'growth.clarityPurposeProposal', 'growth.clarityFieldSearchDescription',
      'growth.clarityFieldSearchTitle', 'growth.clarityFieldArticleSummary', 'growth.clarityFieldArticleText',
      'growth.clarityFieldContent', 'growth.clarityFieldTitle', 'growth.clarityFieldAuthor',
      'growth.clarityFieldFeaturedImage', 'growth.clarityFieldImageDescription', 'growth.clarityFieldImage',
      'growth.clarityFieldImageUrl', 'growth.clarityFieldImageFile', 'growth.clarityFieldPageAddress',
      'growth.clarityFieldDescription', 'growth.clarityFieldName', 'growth.clarityFieldCaption',
      'growth.clarityFieldSearchPhrase', 'growth.clarityFieldWidth', 'growth.clarityFieldHeight',
      'growth.clarityRichTextDetails', 'growth.clarityUnderlined', 'growth.clarityLinkDestination', 'growth.clarityOpensNewTab',
      'growth.clarityRelatedFields', 'growth.clarityScopeDetails', 'growth.clarityRelatedDecisionHeading', 'growth.clarityRelatedDecisionPurpose',
      'growth.clarityShortDescriptionGroupHeading', 'growth.clarityRelatedGroupHeading', 'growth.clarityRelatedGroupFields',
      'growth.clarityReviewChanges', 'growth.clarityOwnerQuestionSubtitle', 'growth.clarityReviewIntroduction']) {
      assert.equal(typeof growthCopy[language][key], 'string', `${language}: ${key}`)
      assert.ok(growthCopy[language][key].length > 0)
    }
    assert.ok(growthCopy[language]['growth.clarityReviewIntroduction'].includes('{fields}'));
  }
  for (const language of ['en', 'fr', 'es']) {
    assert.match(growthCopy[language]['growth.workIntro'], /Ada/);
    assert.doesNotMatch(growthCopy[language]['growth.workIntro'], /decision|décision/iu);
  }
  assert.notEqual(growthCopy.fr['growth.clarityShortDescriptionGroupHeading'], growthCopy.en['growth.clarityShortDescriptionGroupHeading']);
  assert.notEqual(growthCopy.es['growth.clarityShortDescriptionGroupHeading'], growthCopy.en['growth.clarityShortDescriptionGroupHeading']);
})
