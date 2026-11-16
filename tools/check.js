// Every check and test in one go: npm run check (from tools/). Stops at the first failure and says which.
const { spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const win = process.platform === 'win32';
const venv = (name) => path.join(ROOT, 'venv', win ? 'Scripts' : 'bin', win ? `${name}.exe` : name);
const bin = (name) => path.join(__dirname, 'node_modules', '.bin', win ? `${name}.cmd` : name);

// Environment for Django commands: no DJANGO_* from the caller, so nothing leaks in by accident.
const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('DJANGO_')));
// Throwaway production-like values: check --deploy only reads the settings, it needs no database.
const prodEnv = { ...cleanEnv, DJANGO_SECRET_KEY: crypto.randomBytes(48).toString('base64url'), DJANGO_ALLOWED_HOSTS: 'example.com', DJANGO_DB_NAME: 'settings_check_only' };

const steps = [
  ['ruff (Python mistakes and security rules)', venv('ruff'), ['check', '.'], ROOT],
  ['ESLint (front-end code)', bin('eslint'), ['-c', 'tools/eslint.config.js', 'sheet/static/sheet/js'], ROOT],
  ['pip-audit (known holes in Python packages)', venv('pip-audit'), ['-r', 'requirements.txt'], ROOT],
  ['npm audit (known holes in the test tools)', win ? 'npm.cmd' : 'npm', ['audit', '--omit=optional'], __dirname],
  ['Django production settings check', venv('python'), ['manage.py', 'check', '--deploy', '--fail-level', 'WARNING'], ROOT, prodEnv],
  ['backend tests', venv('python'), ['manage.py', 'test', 'sheet'], ROOT, cleanEnv],
  ['parser tests', process.execPath, ['parsing_test.js'], __dirname],
];
if (fs.existsSync(path.join(__dirname, 'dom_test.js'))) steps.push(['element builder tests', process.execPath, ['dom_test.js'], __dirname]);

for (const [label, command, args, cwd, env = process.env] of steps) {
  console.log(`\n=== ${label} ===`);
  // .cmd files can only be started through the shell on Windows; every argument here is a fixed string.
  const result = spawnSync(command, args, { cwd, env, stdio: 'inherit', shell: win && command.endsWith('.cmd') });
  if (result.status !== 0) {
    console.error(`\nFAILED: ${label}`);
    process.exit(1);
  }
}
console.log('\nAll checks passed.');
