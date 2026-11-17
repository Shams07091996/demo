// Unit tests for js/pdfReader.js with a fake Worker, fake Trusted Types and a stub PDF.js (no browser needed).
// What matters: a worker that fails to load makes the read FAIL (it must not hang), and a later read can try again.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildSync } = require('esbuild');
const { JSDOM } = require('jsdom');

const json = (id, value) => `<script type="application/json" id="${id}">${JSON.stringify(value)}</script>`;
// The stub PDF.js: getDocument never settles in "hang" mode (as PDF.js does when its worker never answers).
const stub = `export const GlobalWorkerOptions = {};
export function getDocument() {
  if (globalThis.__pdfMode === 'hang') return { promise: new Promise(() => {}) };
  return { promise: Promise.resolve({ numPages: 1, getPage: async () => ({ getTextContent: async () => ({ items: [{ str: 'HELLO' }] }) }) }) };
}`;
const lib = `data:text/javascript,${encodeURIComponent(stub)}`;
const { window } = new JSDOM(`<!doctype html><body data-pdf-lib="${lib}" data-pdf-worker="/static/w.mjs">
  ${json('me-data', {})}${json('ports-data', [])}${json('types-data', [])}${json('summary-fields-data', [])}
  ${json('option-kinds-data', [])}${json('time-fields-data', [])}</body>`);
global.window = window;
global.document = window.document;

// Fake Trusted Types: like the browser, a second policy with the same name is refused.
const policies = new Set();
window.trustedTypes = {
  createPolicy(name, rules) {
    if (policies.has(name)) throw new TypeError(`Policy "${name}" already exists`);
    policies.add(name);
    return { createScriptURL: (v) => ({ trusted: rules.createScriptURL(v) }) };
  },
};

// Fake Worker: "error" fires an error event soon after starting, "throw" throws, "ok" stays quiet.
let workerMode = 'ok';
let started = 0;
global.Worker = class {
  constructor(url) {
    started += 1;
    if (workerMode === 'throw') throw new Error('cannot start');
    this.url = url;
    this.listeners = {};
    if (workerMode === 'error') setTimeout(() => (this.listeners.error || []).forEach((f) => f(new window.Event('error'))), 20);
  }
  addEventListener(type, f) { (this.listeners[type] ||= []).push(f); }
  removeEventListener(type, f) { this.listeners[type] = (this.listeners[type] || []).filter((g) => g !== f); }
  terminate() { this.terminated = true; }
};

const code = buildSync({
  entryPoints: [path.join(__dirname, '../sheet/static/sheet/js/pdfReader.js')],
  bundle: true, write: false, format: 'cjs', platform: 'node', logLevel: 'error',
}).outputFiles[0].text;
const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pdfreader-')), 'pdfReader.cjs');
fs.writeFileSync(file, code);
const { extractPdfText } = require(file);

let failed = 0;
const check = (cond, label) => { console.log(`${cond ? 'PASS' : 'FAIL'} ${label}`); if (!cond) failed += 1; };
const pdfFile = { arrayBuffer: async () => new ArrayBuffer(8) };
const settle = (promise, ms = 1000) => Promise.race([
  promise.then((v) => ({ ok: v }), (e) => ({ error: e.message })),
  new Promise((r) => setTimeout(() => r({ hung: true }), ms)),
]);

(async () => {
  workerMode = 'throw'; global.__pdfMode = 'ok';
  const cannotStart = await settle(extractPdfText(pdfFile));
  check(cannotStart.error === 'cannot start', `a worker that cannot start makes the read fail (${JSON.stringify(cannotStart)})`);
  started = 0;

  workerMode = 'error'; global.__pdfMode = 'hang';
  const broken = await settle(extractPdfText(pdfFile));
  check(broken.error && /worker/i.test(broken.error), `a worker that fails to load makes the read fail, not hang (${JSON.stringify(broken)})`);

  workerMode = 'ok'; global.__pdfMode = 'ok';
  const retry = await settle(extractPdfText(pdfFile));
  check(retry.ok === 'HELLO\n', `after a failed worker, the next read starts a new one and works (${JSON.stringify(retry)})`);
  check(started === 2, `a new worker was started (${started})`);

  const again = await settle(extractPdfText(pdfFile));
  check(again.ok === 'HELLO\n' && started === 2, 'a working worker is reused');

  console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
  process.exit(failed ? 1 : 0);
})();
