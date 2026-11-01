import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const hasWords = (value) => /[\p{L}\p{N}]/u.test(String(value || ''))

const stringValue = (node, ts) => {
  if (!node) return undefined
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  return undefined
}

const resolveString = (node, declarations, ts, seen = new Set()) => {
  const direct = stringValue(node, ts)
  if (direct !== undefined) return direct
  if (ts.isIdentifier(node) && !seen.has(node.text)) {
    const initializer = declarations.get(node.text)
    if (!initializer) return undefined
    seen.add(node.text)
    return resolveString(initializer, declarations, ts, seen)
  }
  if ((ts.isAsExpression(node) || ts.isParenthesizedExpression(node)) && node.expression) {
    return resolveString(node.expression, declarations, ts, seen)
  }
  return undefined
}

const stringArgument = (node, index, declarations, ts) => {
  const argument = node?.arguments?.[index]
  return argument ? resolveString(argument, declarations, ts) : undefined
}

const propertyInitializer = (node, propertyName, declarations, ts, seen = new Set()) => {
  if (!node || seen.has(node)) return undefined
  seen.add(node)
  if (ts.isIdentifier(node)) return propertyInitializer(declarations.get(node.text), propertyName, declarations, ts, seen)
  if (!ts.isObjectLiteralExpression(node)) return undefined
  for (const item of [...node.properties].reverse()) {
    if (ts.isPropertyAssignment(item) && item.name.getText() === propertyName) return item.initializer
    if (ts.isShorthandPropertyAssignment(item) && item.name.getText() === propertyName) return item.name
    if (ts.isSpreadAssignment(item)) {
      const found = propertyInitializer(item.expression, propertyName, declarations, ts, seen)
      if (found) return found
    }
  }
  return undefined
}

const helperCall = (node, ts, seen = new Set()) => {
  if (!node || seen.has(node)) return undefined
  seen.add(node)
  if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)
      && ['helloAdaBindingId', 'helloAdaGlobalBindingId'].includes(node.expression.text)) return node
  let found
  ts.forEachChild(node, (child) => { found ||= helperCall(child, ts, seen) })
  return found
}

const bindingDescriptor = (expression, declarations, ts, seen = new Set()) => {
  if (!expression || seen.has(expression)) return undefined
  seen.add(expression)
  if (ts.isIdentifier(expression)) {
    const initializer = declarations.get(expression.text)
    if (initializer && ts.isArrowFunction(initializer)) {
      const call = helperCall(initializer.body, ts)
      if (!call) return undefined
      if (call.expression.text === 'helloAdaGlobalBindingId') {
        return { kind: 'global', global: stringArgument(call, 0, declarations, ts), field: stringArgument(call, 2, declarations, ts) }
      }
      const target = call.arguments[2]
      const rawField = propertyInitializer(target, 'field', declarations, ts)
      const parameter = initializer.parameters[0]
      let field
      if (rawField && ts.isIdentifier(rawField) && parameter && ts.isIdentifier(parameter.name)) {
        field = undefined
      } else if (rawField) {
        field = stringValue(rawField, ts)
      }
      return { kind: 'collection', collection: stringArgument(call, 0, declarations, ts), field }
    }
    return bindingDescriptor(initializer, declarations, ts, seen)
  }
  if (!ts.isCallExpression(expression) || !ts.isIdentifier(expression.expression)) return undefined
  const name = expression.expression.text
  if (name === 'helloAdaGlobalBindingId') {
    return {
      kind: 'global',
      global: stringArgument(expression, 0, declarations, ts),
      field: stringArgument(expression, 2, declarations, ts),
    }
  }
  if (name === 'helloAdaBindingId') {
    return {
      kind: 'collection',
      collection: stringArgument(expression, 0, declarations, ts),
      field: stringValue(propertyInitializer(expression.arguments[2], 'field', declarations, ts), ts),
    }
  }
  if (name === 'bind') {
    const initializer = declarations.get('bind')
    if (!initializer || !ts.isArrowFunction(initializer)) return undefined
    const call = helperCall(initializer.body, ts)
    if (!call || !ts.isIdentifier(call.expression) || call.expression.text !== 'helloAdaBindingId') return undefined
    const parameter = initializer.parameters[0]
    const rawField = propertyInitializer(call.arguments[2], 'field', declarations, ts)
    const field = parameter && ts.isIdentifier(parameter.name) && rawField && ts.isIdentifier(rawField) && rawField.text === parameter.name.text
      ? stringArgument(expression, 0, declarations, ts)
      : stringValue(rawField, ts)
    return { kind: 'collection', collection: stringArgument(call, 0, declarations, ts), field }
  }
  return undefined
}

const bindingMatchesContract = (descriptor, contract) => {
  if (!descriptor?.field) return false
  if (descriptor.kind === 'global') {
    const globals = contract.globals || {}
    if (descriptor.global && Array.isArray(globals[descriptor.global]) && globals[descriptor.global].includes(descriptor.field)) return true
    return ['label', 'href'].includes(descriptor.field)
      && Array.isArray(globals.navigation)
      && ['items', 'footer', 'groups', 'footerGroups'].some((field) => globals.navigation.includes(field))
  }
  const collections = contract.collections || {}
  if (descriptor.collection && Array.isArray(collections[descriptor.collection])) {
    if (collections[descriptor.collection].includes(descriptor.field)) return true
    return ['entry', 'item', 'sectionLabel'].includes(descriptor.field)
      && collections[descriptor.collection].includes('sections')
  }
  return Object.values(collections).some((fields) =>
    Array.isArray(fields) && (fields.includes(descriptor.field)
      || (['entry', 'item', 'sectionLabel'].includes(descriptor.field) && fields.includes('sections'))))
}

const renderedText = (node, declarations, ts) => {
  const direct = stringValue(node, ts)
  if (direct !== undefined) return [direct]
  if (ts.isIdentifier(node)) {
    const value = declarations.get(node.text)
    return value === undefined ? [] : renderedText(value, declarations, ts)
  }
  if (ts.isTemplateExpression(node)) {
    return [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
  }
  if (ts.isConditionalExpression(node)) {
    return [
      ...renderedText(node.whenTrue, declarations, ts),
      ...renderedText(node.whenFalse, declarations, ts),
    ]
  }
  if (ts.isBinaryExpression(node) && [ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken].includes(node.operatorToken.kind)) {
    return renderedText(node.right, declarations, ts)
  }
  return []
}

const addViolation = (violations, sourceFile, node, reason) => {
  const point = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
  violations.push({ path: sourceFile.fileName, line: point.line + 1, reason })
}

export function scanPresentation(root, ts) {
  const directory = path.resolve(root)
  if (!fs.statSync(directory).isDirectory()) throw new Error('source inventory root is not a directory')
  const sharedSourcePaths = [
    path.join(directory, 'src/components/site/TenantChrome.tsx'),
    path.join(directory, 'src/components/site/TenantSections.tsx'),
  ]
  const presentationRoot = path.join(directory, 'src/components/site/presentation')
  const presentationFiles = []
  const walk = (current) => {
    if (!fs.existsSync(current)) return
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const resolved = path.join(current, entry.name)
      if (entry.isDirectory()) walk(resolved)
      else if (entry.isFile() && /\.tsx$/i.test(entry.name)) presentationFiles.push(resolved)
    }
  }
  walk(presentationRoot)

  const files = [...new Set([...sharedSourcePaths, ...presentationFiles])]
    .filter((file) => fs.existsSync(file)).sort()
  const contractPath = path.join(directory, 'helloada-content-contract.json')
  if (!fs.existsSync(contractPath)) throw new Error('the shared HelloAda content contract is missing')
  const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'))
  const violations = []
  const bindings = []
  let imageElements = 0
  let editableImages = 0

  for (const file of files) {
    const enforcePayloadCopy = file.startsWith(`${presentationRoot}${path.sep}`)
    const source = fs.readFileSync(file, 'utf8')
    const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    if (sourceFile.parseDiagnostics.length) {
      const diagnostic = sourceFile.parseDiagnostics[0]
      addViolation(violations, sourceFile, diagnostic, 'invalid_presentation_syntax')
      continue
    }

    const declarations = new Map()
    const hasSharedBindingHelper = /helloAda(?:Global)?BindingId/.test(source)
    const gather = (node) => {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
        if (node.initializer) declarations.set(node.name.text, node.initializer)
      }
      ts.forEachChild(node, gather)
    }
    gather(sourceFile)

    // Marker props are bound by the composing file, which owns the shared
    // helper and the document identity. Collect the parameters of enclosing
    // component functions so `data-helloada-field={marker}` is recognised as a
    // reference to that binding rather than an unbindable literal.
    const componentProps = new Set()
    const collectProps = (node) => {
      const isComponent = ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node)
      if (isComponent) {
        for (const parameter of node.parameters) {
          if (ts.isIdentifier(parameter.name)) componentProps.add(parameter.name.text)
          if (ts.isObjectBindingPattern(parameter.name)) {
            for (const element of parameter.name.elements) {
              if (ts.isIdentifier(element.name)) componentProps.add(element.name.text)
            }
          }
        }
      }
      ts.forEachChild(node, collectProps)
    }
    collectProps(sourceFile)

    const inspect = (node) => {
      if (enforcePayloadCopy && ts.isJsxText(node) && hasWords(node.text)) {
        addViolation(violations, sourceFile, node, 'visible_copy_must_come_from_payload')
      }
      if (enforcePayloadCopy && ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
        if (renderedText(node.expression, declarations, ts).some(hasWords)) {
          addViolation(violations, sourceFile, node, 'visible_copy_must_come_from_payload')
        }
      }
      if (ts.isJsxAttribute(node)) {
        const attribute = node.name.getText(sourceFile).toLowerCase()
        if (enforcePayloadCopy && ['alt', 'title', 'placeholder'].includes(attribute) && ts.isStringLiteral(node.initializer) && hasWords(node.initializer.text)) {
          addViolation(violations, sourceFile, node, 'visible_copy_must_come_from_payload')
        }
        if (attribute === 'data-helloada-field') {
          const expression = node.initializer && ts.isJsxExpression(node.initializer) ? node.initializer.expression : undefined
          // A literal can never be a binding, even through a local constant.
          const literal = !expression || resolveString(expression, declarations, ts) !== undefined
          const markerProp = Boolean(expression && ts.isIdentifier(expression) && componentProps.has(expression.text)
            && !declarations.has(expression.text))
          if (literal || (!hasSharedBindingHelper && !markerProp)) {
            addViolation(violations, sourceFile, node, 'editable_field_needs_a_shared_binding')
          } else if (!markerProp) {
            const descriptor = bindingDescriptor(expression, declarations, ts)
            // A computed marker (for example a mapped entry marker) cannot be
            // resolved statically; it is accepted because this file owns the
            // shared helper. A resolvable descriptor must match the contract.
            if (descriptor && !bindingMatchesContract(descriptor, contract)) {
              addViolation(violations, sourceFile, node, 'editable_field_is_outside_the_shared_schema')
            }
            bindings.push({
              path: path.relative(directory, file).split(path.sep).join('/'),
              expression: expression.getText(sourceFile).slice(0, 240),
              target: descriptor || null,
            })
          }
        }
        if (attribute === 'dangerouslysetinnerhtml') {
          addViolation(violations, sourceFile, node, 'raw_html_is_not_an_editable_content_binding')
        }
      }
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        if (node.tagName.getText(sourceFile).toLowerCase() === 'img') {
          imageElements += 1
          let editable = false
          let owner = node
          while (owner) {
            const opening = ts.isJsxElement(owner) ? owner.openingElement : owner
            if ((ts.isJsxOpeningElement(opening) || ts.isJsxSelfClosingElement(opening))
              && opening.attributes.properties.some((property) =>
                ts.isJsxAttribute(property) && property.name.getText(sourceFile) === 'data-helloada-field')) {
              editable = true
              break
            }
            owner = owner.parent
          }
          if (editable) {
            editableImages += 1
          } else {
            addViolation(violations, sourceFile, node, 'business_image_needs_a_shared_payload_binding')
          }
        }
      }
      ts.forEachChild(node, inspect)
    }
    inspect(sourceFile)
  }

  violations.sort((left, right) => left.path.localeCompare(right.path) || left.line - right.line || left.reason.localeCompare(right.reason))
  return {
    version: 2,
    filesScanned: files.length,
    editableCount: bindings.length,
    dynamicCount: bindings.length,
    bindingCount: bindings.length,
    editableImages,
    imageElements,
    fields: bindings,
    violations,
  }
}

async function main() {
  const rootIndex = process.argv.indexOf('--root')
  if (rootIndex < 0 || !process.argv[rootIndex + 1]) throw new Error('--root is required')
  const root = path.resolve(process.argv[rootIndex + 1])
  const require = (await import('node:module')).createRequire(path.join(root, 'package.json'))
  const ts = require('typescript')
  const result = scanPresentation(root, ts)
  process.stdout.write(`${JSON.stringify(result)}\n`)
  if (result.violations.length) process.exitCode = 2
}

const calledDirectly = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href
if (calledDirectly) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : 'source inventory failed'}\n`)
    process.exitCode = 1
  })
}
