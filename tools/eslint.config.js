// ESLint for the app's own browser code. Run: npm run lint
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
      // Screens are built with dom.js only: no HTML strings may be parsed anywhere.
      'no-restricted-properties': ['error',
        ...['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'createContextualFragment', 'setHTMLUnsafe', 'write', 'writeln']
          .map((property) => ({ property, message: 'Build elements with h() from dom.js instead of HTML strings.' })),
      ],
      'no-restricted-syntax': ['error',
        { selector: "MemberExpression[property.name=/^(innerHTML|outerHTML|srcdoc)$/]", message: 'Build elements with h() from dom.js.' },
        { selector: "Property[key.name=/^(innerHTML|outerHTML|srcdoc)$/]", message: 'Build elements with h() from dom.js.' },
        { selector: "CallExpression[callee.property.name='setAttribute'][arguments.0.value=/^(on|style$|srcdoc$)/i]", message: 'No event-handler, style or srcdoc attributes.' },
      ],
      'no-restricted-globals': ['error',
        { name: 'DOMParser', message: 'No HTML parsing: build elements with h() from dom.js.' },
        { name: 'Range', message: 'No HTML parsing: build elements with h() from dom.js.' },
      ],
    },
  },
];
