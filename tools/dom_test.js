// Unit tests for the element builder (js/dom.js): values only ever go in as text or allowed attributes.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { buildSync } = require('esbuild');
const { JSDOM } = require('jsdom');

const { window } = new JSDOM('<!doctype html><body></body>');
global.document = window.document;
global.Node = window.Node;

const code = buildSync({
  entryPoints: [path.join(__dirname, '../sheet/static/sheet/js/dom.js')],
  bundle: true, write: false, format: 'cjs', logLevel: 'error',
}).outputFiles[0].text;
const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'dom-')), 'dom.cjs');
fs.writeFileSync(file, code);
const { h, frag, setChildren, optionEls } = require(file);

let failed = 0;
const check = (cond, label) => { console.log(`${cond ? 'PASS' : 'FAIL'} ${label}`); if (!cond) failed += 1; };
const throws = (fn) => { try { fn(); return false; } catch { return true; } };

const hostile = '<img src=x onerror=alert(1)>';
const td = h('td', null, hostile);
check(td.querySelector('img') === null && td.textContent === hostile, 'markup in a value stays text');
check(h('td', null, 'a &amp; b').textContent === 'a &amp; b', 'entities are not decoded');

check(throws(() => h('a', { href: 'javascript:alert(1)' })), 'javascript: href refused');
check(throws(() => h('a', { href: ' JaVaScRiPt:alert(1)' })), 'javascript: href refused whatever the case / spaces');
check(throws(() => h('a', { href: 'data:text/html,x' })), 'data: href refused');
check(throws(() => h('a', { href: '//evil.example/x' })), 'protocol-relative href refused');
check(throws(() => h('a', { href: '\\\\evil.example' })), 'backslash host href refused');
check(h('a', { href: '#vessels' }).getAttribute('href') === '#vessels', '#hash href allowed');
check(h('a', { href: 'https://example.com/x' }).getAttribute('href') === 'https://example.com/x', 'https href allowed');
check(h('a', { href: '/api/export/' }).getAttribute('href') === '/api/export/', 'relative href allowed');
check(throws(() => h('div', { attrs: { onclick: 'x' } })), 'on* attribute refused');
check(throws(() => h('div', { attrs: { ONCLICK: 'x' } })), 'on* attribute refused whatever the case');
check(throws(() => h('iframe', { attrs: { srcdoc: 'x' } })), 'srcdoc refused');
check(throws(() => h('div', { attrs: { style: 'color:red' } })), 'style attribute string refused');
check(throws(() => h('div', { nonsense: 1 })), 'unknown prop refused');
check(throws(() => h('script')), 'script element refused');
check(throws(() => h('div', { attrs: { 'data-x': '1' } })), 'data-* only through dataset');

const btn = h('button', { class: 'btn small', dataset: { act: 'summary', id: 5 } }, 'Go');
check(btn.className === 'btn small' && btn.dataset.act === 'summary' && btn.dataset.id === '5', 'class and dataset');
check(h('td', { attrs: { colspan: 3, 'aria-label': 'x', title: 'T' } }).getAttribute('colspan') === '3', 'allowed attributes set');
check(h('td', { attrs: { title: null } }).hasAttribute('title') === false, 'null attribute skipped');

const input = h('input', { attrs: { type: 'text' }, value: 'a"b', disabled: true });
check(input.value === 'a"b' && input.disabled === true, 'value and disabled are properties');
check(h('input', { value: null }).value === '', 'null value becomes empty');
check(h('input', { attrs: { type: 'checkbox' }, checked: true }).checked === true, 'checked property');
check(h('details', { open: true }).open === true && h('details', { open: false }).open === false, 'open property');
check(h('input', { attrs: { autofocus: true } }).hasAttribute('autofocus'), 'autofocus attribute');

const box = h('div', { style: { display: 'none', borderTopColor: 'rgb(1, 2, 3)' } });
check(box.style.display === 'none' && box.style.borderTopColor === 'rgb(1, 2, 3)', 'style object through el.style');

check(h('td', null, null, undefined, false, 0, ['a', ['b']]).textContent === '0ab', 'children: skip empty, keep 0, flatten');
check(h('div', null, h('b', null, 'x')).firstChild.tagName === 'B', 'element children kept');

const f = frag('a', h('i', null, 'b'));
check(f.nodeType === 11 && f.childNodes.length === 2, 'frag builds a fragment');

const host = h('div', null, 'old');
setChildren(host, 'new', h('span'));
check(host.textContent === 'new' && host.childNodes.length === 2, 'setChildren replaces the content');
setChildren(host);
check(host.childNodes.length === 0, 'setChildren with nothing empties it');

const opts = optionEls([['', 'All'], ['x', '<b>']], 'x');
check(opts.length === 2 && opts[1].selected && !opts[0].selected, 'optionEls selects the current value');
check(opts[1].textContent === '<b>' && opts[1].value === 'x', 'option label stays text');

console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
process.exit(failed ? 1 : 0);
