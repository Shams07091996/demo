// The only way screens are built: elements from h(), with every dynamic value inserted as TEXT (a text node) or as
// an allowed attribute / property. No HTML string is ever parsed, so typed text can never become markup or script.
// Anything not on the lists below throws, so a mistake shows up in the tests instead of becoming a hole.

const ATTRS = new Set([
  'id', 'class', 'title', 'type', 'name', 'for', 'colspan', 'rowspan', 'min', 'max', 'step', 'maxlength',
  'placeholder', 'rows', 'role', 'tabindex', 'href', 'target', 'rel', 'autocomplete', 'inputmode', 'readonly',
  'multiple', 'accept', 'list', 'autofocus', 'src', 'alt',
]);
const PROPS = new Set(['value', 'checked', 'selected', 'disabled', 'hidden', 'open']);
const BLOCKED_TAGS = new Set(['script', 'iframe', 'frame', 'object', 'embed', 'style', 'link', 'meta', 'base', 'template']);
// '#…', relative paths and http(s) only: no javascript:, data:, vbscript: … (control characters and spaces ignored,
// as browsers do). Two leading slashes / backslashes would mean another host, so they are refused too.
const SAFE_URL = /^(?![/\\]{2})(#|\.{0,2}[/\\]|https?:\/\/|[^:]*$)/i;

function setAttr(el, name, value) {
  const key = name.toLowerCase();
  if (!(ATTRS.has(key) || key.startsWith('aria-'))) throw new Error(`h(): attribute "${name}" is not allowed`);
  if (value === null || value === undefined || value === false) return;
  const text = value === true ? '' : String(value);
  // eslint-disable-next-line no-control-regex
  if ((key === 'href' || key === 'src') && !SAFE_URL.test(text.replace(/[\u0000- ]/g, ''))) throw new Error(`h(): unsafe ${key}`);
  el.setAttribute(key, text);
}

function append(parent, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) child.forEach((c) => append(parent, c));
  else if (child instanceof Node) parent.appendChild(child);
  else parent.appendChild(document.createTextNode(String(child)));
}

/**
 * h('td', { class, id, dataset: {act: 'x'}, style: {display: 'none'}, attrs: {title: 'T'}, value, disabled }, ...children)
 * Children: nodes, strings / numbers (become text), arrays (flattened); null / undefined / false are skipped.
 */
export function h(tag, props, ...children) {
  if (BLOCKED_TAGS.has(String(tag).toLowerCase())) throw new Error(`h(): <${tag}> is not allowed`);
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === 'class') { if (value) el.className = value; }
    else if (key === 'id') setAttr(el, 'id', value);
    else if (key === 'href') setAttr(el, 'href', value);
    else if (key === 'dataset') {
      for (const [k, v] of Object.entries(value || {})) if (v !== null && v !== undefined) el.dataset[k] = String(v);
    } else if (key === 'style') Object.assign(el.style, value || {});
    else if (key === 'attrs') for (const [k, v] of Object.entries(value || {})) setAttr(el, k, v);
    else if (PROPS.has(key)) el[key] = key === 'value' ? (value ?? '') : Boolean(value);
    else throw new Error(`h(): unknown prop "${key}"`);
  }
  append(el, children);
  return el;
}

export function frag(...children) {
  const f = document.createDocumentFragment();
  append(f, children);
  return f;
}

/** Replace everything inside el with the given children (same rules as h()). */
export function setChildren(el, ...children) {
  el.replaceChildren(frag(...children));
}

/** The icons drawn in templates/sheet/icons.svg (one <symbol id="i-NAME"> each; sheet/tests_look.py keeps them equal). */
export const ICONS = Object.freeze([
  'anchor', 'ship', 'bed', 'car', 'calculator', 'chart', 'database', 'swap', 'clock', 'key', 'log-out', 'bell', 'trash',
  'pencil', 'plus', 'x', 'check', 'alert', 'menu', 'sun', 'moon', 'chevron-down', 'chevron-up', 'sort', 'calendar',
  'users', 'printer', 'file', 'phone', 'ban', 'lock',
]);
const SVG_NS = 'http://www.w3.org/2000/svg';
const ICON_NAME = /^[a-z0-9-]+$/;

/**
 * <svg class="ic" aria-hidden="true"><use href="#i-NAME"></use></svg>, pointing at the page's own sprite. Only a
 * known name is accepted, so this can never put any other URL into the page; h() itself stays HTML-only.
 */
export function icon(name, cls = '') {
  if (typeof name !== 'string' || !ICON_NAME.test(name) || !ICONS.includes(name)) throw new Error(`icon(): unknown icon "${name}"`);
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', cls ? `ic ${cls}` : 'ic');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

/** <option> elements from [value, label] pairs; the one equal to `selected` is selected. */
export const optionEls = (pairs, selected) =>
  pairs.map(([value, label]) => h('option', { value, selected: String(value) === String(selected ?? '') }, label));
