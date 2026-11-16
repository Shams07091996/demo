// ESLint for the app's own browser code (not the vendored PDF.js). Run: npm run lint
const js = require('@eslint/js');
const globals = require('globals');

module.exports = [
  {
    files: ['sheet/static/sheet/js/**/*.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'module', globals: globals.browser },
    rules: {
      ...js.configs.recommended.rules,
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-unused-vars': ['error', { ignoreRestSiblings: true }],
    },
  },
];
