// @ts-check
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

/* Three product invariants are enforced here as RULES rather than as review
 * habits, because a convention is only as good as the reviewer who is tired.
 *
 * 1. NEVER dangerouslySetInnerHTML. This product renders text that came from a
 *    PLC, a tmux pane, a Jira summary and an agent's own output. Every one of
 *    those is attacker-adjacent input in the only sense that matters: nobody on
 *    this team wrote it. React escapes by default and that default is the whole
 *    defence, so the escape hatch is closed at the linter. It is banned in both
 *    spellings - the JSX attribute and the createElement props key - because
 *    banning only the first leaves the second as a legal way to do it.
 *
 * 2. NEVER a browser confirm()/alert()/prompt(). A modal dialog blocks the page,
 *    which in this product means it blocks a terminal stream and the panel that
 *    would show the operator the dry run they are being asked to approve. The
 *    blade renders confirmations as cards for exactly that reason. Banned as
 *    bare globals AND as window.* members, since window.confirm() sails past
 *    no-restricted-globals.
 *
 * 3. NEVER a colour literal in a component. design/tokens.css is the one file
 *    where a colour is decided, and a #hex in a .tsx is how that stops being
 *    true. The CSS half of this rule is not expressible in ESLint and lives in
 *    scripts/check-literals.mjs instead.
 */
const NO_DANGER = 'Never dangerouslySetInnerHTML. Render text as text; React escapes it. If markup is genuinely required, parse it into elements.';
const NO_DIALOG = 'Browser dialogs are banned product-wide: they block the page and cannot render a dry run. Use an inline confirmation card in the blade.';
const NO_HEX = 'No colour literal in source. Add the token to design/tokens.css and read it with var().';

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', '**/*.css'] },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        localStorage: 'readonly',
        performance: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        console: 'readonly',
        HTMLElement: 'readonly',
        HTMLDivElement: 'readonly',
        HTMLButtonElement: 'readonly',
        HTMLSpanElement: 'readonly',
        PointerEvent: 'readonly',
        KeyboardEvent: 'readonly',
        IntersectionObserver: 'readonly',
        queueMicrotask: 'readonly',
      },
    },
    rules: {
      'no-alert': 'error',

      'no-restricted-globals': [
        'error',
        { name: 'confirm', message: NO_DIALOG },
        { name: 'alert', message: NO_DIALOG },
        { name: 'prompt', message: NO_DIALOG },
      ],

      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'confirm', message: NO_DIALOG },
        { object: 'window', property: 'alert', message: NO_DIALOG },
        { object: 'window', property: 'prompt', message: NO_DIALOG },
        { object: 'globalThis', property: 'confirm', message: NO_DIALOG },
        { object: 'globalThis', property: 'alert', message: NO_DIALOG },
        { object: 'globalThis', property: 'prompt', message: NO_DIALOG },
      ],

      'no-restricted-syntax': [
        'error',
        { selector: 'JSXAttribute[name.name="dangerouslySetInnerHTML"]', message: NO_DANGER },
        { selector: 'Property[key.name="dangerouslySetInnerHTML"]', message: NO_DANGER },
        { selector: 'Property[key.value="dangerouslySetInnerHTML"]', message: NO_DANGER },
        {
          selector: 'MemberExpression[property.name="innerHTML"]',
          message: 'Assigning innerHTML is dangerouslySetInnerHTML with extra steps. Use textContent, or build elements.',
        },
        {
          selector: 'Literal[value=/^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/]',
          message: NO_HEX,
        },
      ],

      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
    },
  },

  {
    // The literal checker and the vite config run in Node and may say `process`.
    files: ['scripts/**/*.mjs', 'vite.config.ts'],
    languageOptions: {
      globals: { process: 'readonly', console: 'readonly', URL: 'readonly' },
    },
  },
);
