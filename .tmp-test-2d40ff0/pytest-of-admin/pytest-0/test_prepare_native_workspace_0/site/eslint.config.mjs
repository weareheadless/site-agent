import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { FlatCompat } from '@eslint/eslintrc'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const compat = new FlatCompat({ baseDirectory: __dirname })

export default [
  { ignores: ['.next/**', '.open-next/**', 'out/**', 'dist/**', 'build/**', 'coverage/**', 'node_modules/**', '.opencode/**', '.agent-home/**', '*.tsbuildinfo'] },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
]
