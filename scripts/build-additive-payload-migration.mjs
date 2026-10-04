import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { isDeepStrictEqual } from 'node:util'

const identifier = (value) => `\`${String(value).replaceAll('`', '``')}\``

const snapshotObjectsEqual = (left, right) => isDeepStrictEqual(left, right)

const sqlStatementsFrom = (source) => {
  const statements = []
  const calls = /await db\.run\(sql`/g
  for (const match of source.matchAll(calls)) {
    const start = match.index + match[0].length
    let end = start
    for (; end < source.length; end += 1) {
      if (source[end] === '\\') {
        end += 1
        continue
      }
      if (source[end] === '`') break
    }
    if (end === source.length) throw new Error('Candidate migration contains an unterminated SQL template literal.')
    const statement = source.slice(start, end).replaceAll('\\`', '`').trim()
    if (statement) statements.push(statement)
  }
  return statements
}

const createdTable = (statement) => statement.match(/^CREATE TABLE(?: IF NOT EXISTS)?\s+`([^`]+)`/i)?.[1]

const indexStatement = (tableName, index, name = index.name) => {
  const unique = index.isUnique ? 'UNIQUE ' : ''
  const columns = index.columns.map(identifier).join(', ')
  return `CREATE ${unique}INDEX IF NOT EXISTS ${identifier(name)} ON ${identifier(tableName)} (${columns});`
}

const columnDefinition = (table, columnName, column) => {
  if (column.primaryKey || column.autoincrement) {
    throw new Error(`Cannot add primary-key column ${table.name}.${columnName} without a reviewed table rebuild.`)
  }
  let definition = `${identifier(columnName)} ${column.type}`
  if (column.default !== undefined) {
    const value = typeof column.default === 'boolean' ? (column.default ? '1' : '0') : String(column.default)
    definition += ` DEFAULT ${value}`
  }
  if (column.notNull) {
    if (column.default === undefined) throw new Error(`Cannot add required column ${table.name}.${columnName} without a default.`)
    definition += ' NOT NULL'
  }
  const foreignKeys = Object.values(table.foreignKeys || {}).filter((foreignKey) => foreignKey.columnsFrom?.includes(columnName))
  if (foreignKeys.length > 1) throw new Error(`Ambiguous foreign-key definitions for ${table.name}.${columnName}.`)
  if (foreignKeys.length === 1) {
    const foreignKey = foreignKeys[0]
    if (foreignKey.columnsFrom.length !== 1 || foreignKey.columnsTo.length !== 1) {
      throw new Error(`Composite foreign key on ${table.name}.${columnName} cannot be added without a reviewed table rebuild.`)
    }
    if (foreignKey.columnsFrom[0] !== columnName) {
      throw new Error(`Foreign key on ${table.name}.${columnName} also includes existing columns; an explicit reviewed migration is required.`)
    }
    definition += ` REFERENCES ${identifier(foreignKey.tableTo)} (${identifier(foreignKey.columnsTo[0])})`
    if (foreignKey.onDelete && foreignKey.onDelete !== 'no action') definition += ` ON DELETE ${foreignKey.onDelete.toUpperCase()}`
    if (foreignKey.onUpdate && foreignKey.onUpdate !== 'no action') definition += ` ON UPDATE ${foreignKey.onUpdate.toUpperCase()}`
  }
  return definition
}

const assertNoUnrepresentedTableConstraints = (before, after, tableName) => {
  const old = before.tables[tableName]
  const current = after.tables[tableName]
  for (const constraintType of ['compositePrimaryKeys', 'uniqueConstraints', 'checkConstraints']) {
    if (!snapshotObjectsEqual(old[constraintType] || {}, current[constraintType] || {})) {
      throw new Error(`Table ${tableName} changes ${constraintType}; an explicit reviewed migration is required.`)
    }
  }
  const oldForeignKeys = old.foreignKeys || {}
  const currentForeignKeys = current.foreignKeys || {}
  for (const [name, foreignKey] of Object.entries(currentForeignKeys)) {
    if (oldForeignKeys[name] && !snapshotObjectsEqual(foreignKey, oldForeignKeys[name])) {
      throw new Error(`Table ${tableName} changes existing foreign key ${name}; an explicit reviewed migration is required.`)
    }
  }
  for (const [name, foreignKey] of Object.entries(currentForeignKeys)) {
    if (oldForeignKeys[name]) continue
    if (foreignKey.columnsFrom.length !== 1 || foreignKey.columnsTo.length !== 1) {
      throw new Error(`Table ${tableName} adds composite foreign key ${name}; an explicit reviewed migration is required.`)
    }
    const columnsWereAlreadyPresent = foreignKey.columnsFrom.every((column) => old.columns[column])
    if (columnsWereAlreadyPresent) throw new Error(`Table ${tableName} adds a foreign key on existing columns; an explicit reviewed migration is required.`)
  }

  for (const [name, column] of Object.entries(old.columns || {})) {
    const next = current.columns?.[name]
    if (!next || snapshotObjectsEqual(column, next)) continue
    const changedKeys = [...new Set([...Object.keys(column), ...Object.keys(next)])]
      .filter((key) => !snapshotObjectsEqual(column[key], next[key]))
    const onlyTightenedRequired = changedKeys.length === 1 && changedKeys[0] === 'notNull' && column.notNull === false && next.notNull === true
    if (!onlyTightenedRequired) {
      throw new Error(`Table ${tableName} changes existing column ${name}; an explicit reviewed migration is required.`)
    }
  }
}

export const buildAdditiveStatements = ({ baseline, target, candidateSource }) => {
  if (baseline.dialect !== 'sqlite' || target.dialect !== 'sqlite') throw new Error('Payload tenant migrations must use SQLite snapshots.')
  if (!baseline.tables || !target.tables) throw new Error('Payload migration snapshots must include tables.')

  const candidateStatements = sqlStatementsFrom(candidateSource)
  const tableCreates = new Map(candidateStatements.map((statement) => [createdTable(statement), statement]).filter(([name]) => name))
  const newTables = Object.keys(target.tables).filter((name) => !baseline.tables[name])
  const statements = []

  for (const name of newTables) {
    const create = tableCreates.get(name)
    if (!create) throw new Error(`Payload diff does not contain the new table ${name}.`)
    statements.push(create.endsWith(';') ? create : `${create};`)
  }

  for (const [tableName, table] of Object.entries(target.tables)) {
    const old = baseline.tables[tableName]
    if (!old) continue
    assertNoUnrepresentedTableConstraints(baseline, target, tableName)
    for (const [columnName, column] of Object.entries(table.columns || {})) {
      if (old.columns[columnName]) continue
      statements.push(`ALTER TABLE ${identifier(tableName)} ADD COLUMN ${columnDefinition(table, columnName, column)};`)
    }
  }

  for (const [tableName, table] of Object.entries(target.tables)) {
    const old = baseline.tables[tableName]
    for (const [indexName, index] of Object.entries(table.indexes || {})) {
      const previous = old?.indexes?.[indexName]
      if (previous && snapshotObjectsEqual(previous, index)) continue
      const existingNameHasDifferentDefinition = Boolean(previous)
      const name = existingNameHasDifferentDefinition ? `${indexName}_helloada` : indexName
      const collision = Object.values(old?.indexes || {}).some((candidate) => candidate.name === name)
      if (collision) {
        throw new Error(`Cannot add canonical index ${indexName}: the safe additive name ${name} is already occupied.`)
      }
      statements.push(indexStatement(tableName, index, name))
    }
  }

  const uniqueStatements = [...new Set(statements)]
  if (!uniqueStatements.length) throw new Error('No additive Payload schema changes were found.')
  return uniqueStatements
}

const tightenedRequiredColumns = (baseline, target) => Object.entries(target.tables).flatMap(([tableName, table]) => {
  const old = baseline.tables[tableName]
  if (!old) return []
  return Object.entries(table.columns || {}).flatMap(([columnName, column]) => (
    old.columns[columnName]?.notNull === false && column.notNull === true
      ? [`${tableName}.${columnName}`]
      : []
  ))
})

const parseArgs = (argv) => {
  const values = new Map()
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index]
    if (!key.startsWith('--') || !argv[index + 1] || argv[index + 1].startsWith('--')) throw new Error(`Invalid argument near ${key}.`)
    values.set(key.slice(2), argv[++index])
  }
  for (const key of ['baseline', 'target', 'candidate', 'output']) if (!values.has(key)) throw new Error(`Missing --${key}.`)
  return values
}

const main = async () => {
  const args = parseArgs(process.argv.slice(2))
  const [baseline, target, candidateSource] = await Promise.all([
    readFile(args.get('baseline'), 'utf8').then(JSON.parse),
    readFile(args.get('target'), 'utf8').then(JSON.parse),
    readFile(args.get('candidate'), 'utf8'),
  ])
  const name = path.basename(args.get('output'), '.ts')
  const statements = buildAdditiveStatements({ baseline, target, candidateSource })
  const migration = [
    "import type { MigrateDownArgs, MigrateUpArgs } from '@payloadcms/db-d1-sqlite'",
    "import { sql } from '@payloadcms/db-d1-sqlite'",
    '',
    'export async function up({ db }: MigrateUpArgs): Promise<void> {',
    ...statements.map((statement) => `  await db.run(sql.raw(${JSON.stringify(statement)}))`),
    '}',
    '',
    'export async function down(_args: MigrateDownArgs): Promise<void> {',
    '  // Payload tenant releases are forward-only; preserve records and prior-worker compatibility.',
    '}',
    '',
  ].join('\n')
  await writeFile(args.get('output'), migration, { flag: 'wx' })
  console.log(`[payload-migration] ${name}: ${statements.length} additive statements`)
  const payloadValidatedColumns = tightenedRequiredColumns(baseline, target)
  if (payloadValidatedColumns.length) {
    console.warn(`[payload-migration] SQLite keeps these existing columns nullable under additive-only DDL; Payload's required-field validation enforces writes: ${payloadValidatedColumns.join(', ')}`)
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`[payload-migration] ${error instanceof Error ? error.message : String(error)}`)
    process.exitCode = 1
  })
}
