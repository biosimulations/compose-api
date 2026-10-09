// @ts-check
import withNuxt from './.nuxt/eslint.config.mjs'

export default withNuxt(
  { ignores: ['app/api/schema.d.ts'] },
  {
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off'
    }
  }
)
