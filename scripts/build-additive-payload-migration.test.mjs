import test from 'node:test'
import assert from 'node:assert/strict'
import { buildAdditiveStatements } from './build-additive-payload-migration.mjs'

const column = (name, overrides = {}) => ({
  name,
  type: 'text',
  primaryKey: false,
  notNull: false,
  autoincrement: false,
  ...overrides,
})

const table = (name, { columns = {}, indexes = {}, foreignKeys = {}, compositePrimaryKeys = {}, uniqueConstraints = {}, checkConstraints = {} } = {}) => ({
  name,
  columns,
  indexes,
  foreignKeys,
  compositePrimaryKeys,
  uniqueConstraints,
  checkConstraints,
})

const snapshot = (tables) => ({ version: '6', dialect: 'sqlite', tables })

const baseline = snapshot({
  pages: table('pages', {
    columns: { id: column('id', { type: 'integer', primaryKey: true, notNull: true }), title: column('title') },
    indexes: { pages_title_idx: { name: 'pages_title_idx', columns: ['title'], isUnique: false } },
  }),
})

test('builds forward-only additive tables, columns, indexes and scalar foreign keys', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: {
        id: column('id', { type: 'integer', primaryKey: true, notNull: true }),
        title: column('title'),
        subtitle: column('subtitle'),
        category_id: column('category_id'),
        migration_version: column('migration_version', { notNull: true, default: '1' }),
      },
      indexes: {
        pages_title_idx: { name: 'pages_title_idx', columns: ['title'], isUnique: false },
        pages_subtitle_idx: { name: 'pages_subtitle_idx', columns: ['subtitle'], isUnique: false },
      },
      foreignKeys: {
        pages_category_id_fk: {
          name: 'pages_category_id_fk',
          tableFrom: 'pages',
          tableTo: 'categories',
          columnsFrom: ['category_id'],
          columnsTo: ['id'],
          onDelete: 'set null',
          onUpdate: 'no action',
        },
      },
    }),
    categories: table('categories', {
      columns: { id: column('id', { type: 'integer', primaryKey: true, notNull: true }) },
      indexes: { categories_id_idx: { name: 'categories_id_idx', columns: ['id'], isUnique: false } },
    }),
  })
  const statements = buildAdditiveStatements({
    baseline,
    target,
    candidateSource: [
      'await db.run(sql`CREATE TABLE \\`categories\\` (',
      '  \\`id\\` integer PRIMARY KEY NOT NULL',
      ');`)',
      'await db.run(sql`CREATE INDEX \\`categories_id_idx\\` ON \\`categories\\` (\\`id\\`);`)',
    ].join('\n'),
  })

  assert.match(statements[0], /^CREATE TABLE `categories`/)
  assert.ok(statements.includes('CREATE INDEX IF NOT EXISTS `categories_id_idx` ON `categories` (`id`);'))
  assert.ok(statements.includes('ALTER TABLE `pages` ADD COLUMN `subtitle` text;'))
  assert.ok(statements.includes('ALTER TABLE `pages` ADD COLUMN `category_id` text REFERENCES `categories` (`id`) ON DELETE SET NULL;'))
  assert.ok(statements.includes('ALTER TABLE `pages` ADD COLUMN `migration_version` text DEFAULT 1 NOT NULL;'))
  assert.ok(statements.includes('CREATE INDEX IF NOT EXISTS `pages_subtitle_idx` ON `pages` (`subtitle`);'))
  assert.ok(statements.every((statement) => !/\bDROP\b|\bRENAME\b/i.test(statement)))
})

test('preserves removed legacy columns and tables without generating destructive SQL', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: { id: column('id', { type: 'integer', primaryKey: true, notNull: true }), subtitle: column('subtitle') },
      indexes: baseline.tables.pages.indexes,
    }),
  })
  const statements = buildAdditiveStatements({ baseline, target, candidateSource: '' })
  assert.deepEqual(statements, ['ALTER TABLE `pages` ADD COLUMN `subtitle` text;'])
})

test('fails on changed existing columns', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: {
        id: column('id', { type: 'integer', primaryKey: true, notNull: true }),
        title: column('title', { type: 'integer' }),
      },
      indexes: { pages_title_idx: { name: 'pages_title_idx', columns: ['title'], isUnique: false } },
    }),
  })
  assert.throws(() => buildAdditiveStatements({ baseline, target, candidateSource: '' }), /changes existing column title/)
})

test('permits tightening an existing nullable column when Payload enforces required writes', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: {
        id: column('id', { type: 'integer', primaryKey: true, notNull: true }),
        title: column('title', { notNull: true }),
      },
      indexes: baseline.tables.pages.indexes,
    }),
  })
  assert.throws(() => buildAdditiveStatements({ baseline, target, candidateSource: '' }), /No additive Payload schema changes/)
  const withAddition = snapshot({
    pages: table('pages', {
      columns: { ...target.tables.pages.columns, summary: column('summary') },
      indexes: baseline.tables.pages.indexes,
    }),
  })
  assert.deepEqual(buildAdditiveStatements({ baseline, target: withAddition, candidateSource: '' }), [
    'ALTER TABLE `pages` ADD COLUMN `summary` text;',
  ])
})

test('keeps retired indexes and adds a distinct canonical index when an index changes', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: baseline.tables.pages.columns,
      indexes: {
        pages_title_idx: { name: 'pages_title_idx', columns: ['title'], isUnique: true },
        pages_new_idx: { name: 'pages_new_idx', columns: ['id'], isUnique: false },
      },
    }),
  })
  const statements = buildAdditiveStatements({ baseline, target, candidateSource: '' })
  assert.ok(statements.includes('CREATE UNIQUE INDEX IF NOT EXISTS `pages_title_idx_helloada` ON `pages` (`title`);'))
  assert.ok(statements.includes('CREATE INDEX IF NOT EXISTS `pages_new_idx` ON `pages` (`id`);'))
  assert.ok(statements.every((statement) => !/\bDROP\b/i.test(statement)))
})

test('fails on required columns without defaults', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: { ...baseline.tables.pages.columns, required: column('required', { notNull: true }) },
      indexes: baseline.tables.pages.indexes,
    }),
  })
  assert.throws(() => buildAdditiveStatements({ baseline, target, candidateSource: '' }), /required column pages.required without a default/)
})

test('fails on composite foreign keys instead of silently omitting them', () => {
  const target = snapshot({
    pages: table('pages', {
      columns: {
        ...baseline.tables.pages.columns,
        tenant_id: column('tenant_id'),
        category_id: column('category_id'),
      },
      indexes: baseline.tables.pages.indexes,
      foreignKeys: {
        pages_category_fk: {
          name: 'pages_category_fk',
          tableFrom: 'pages',
          tableTo: 'categories',
          columnsFrom: ['tenant_id', 'category_id'],
          columnsTo: ['tenant_id', 'id'],
          onDelete: 'cascade',
          onUpdate: 'no action',
        },
      },
    }),
  })
  assert.throws(() => buildAdditiveStatements({ baseline, target, candidateSource: '' }), /adds composite foreign key pages_category_fk/)
})

test('fails if the candidate diff is missing a required new table', () => {
  const target = snapshot({
    ...baseline.tables,
    categories: table('categories', { columns: { id: column('id', { type: 'integer', primaryKey: true, notNull: true }) } }),
  })
  assert.throws(() => buildAdditiveStatements({ baseline, target, candidateSource: '' }), /does not contain the new table categories/)
})
