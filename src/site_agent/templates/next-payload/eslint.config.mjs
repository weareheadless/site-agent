import nextVitals from 'eslint-config-next/core-web-vitals'
import nextTypeScript from 'eslint-config-next/typescript'

export default [
  ...nextVitals,
  ...nextTypeScript,
  {
    ignores: ['.next/**', '.open-next/**', 'node_modules/**', 'src/payload-types.ts'],
  },
]
