// A donut chart as SVG built with createElementNS (no markup strings, no library), plus its legend from dom.js.
// Slices and legend items carry the caller's data-act so a click does what the old bars did.
import { CHART_COLORS } from '../config.js';
import { h } from '../dom.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const MAX_SLICES = 8; // more than this: the top 7 and "Other"
const RADIUS = 60;
const RING = 2 * Math.PI * RADIUS;

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
  return el;
}

/** The items to draw: the biggest first, the tail folded into "Other" (which has no act). */
export function donutItems(items) {
  const sorted = items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  if (sorted.length <= MAX_SLICES) return sorted;
  const rest = sorted.slice(MAX_SLICES - 1).reduce((n, i) => n + i.value, 0);
  return [...sorted.slice(0, MAX_SLICES - 1), { label: 'Other', value: rest, other: true }];
}

/**
 * items: [{label, value}]; dataset(item) gives a slice's data-* (e.g. {act: 'opr-summary', opr}). Returns a
 * `.donut` element: the ring with the total in the middle, and the legend "label  value (pct%)".
 */
export function donutEl(items, { dataset, total: totalLabel }) {
  const shown = donutItems(items);
  const total = shown.reduce((n, i) => n + i.value, 0);
  const svg = svgEl('svg', { viewBox: '0 0 160 160', class: 'donut-ring', role: 'img', 'aria-label': totalLabel });
  svg.appendChild(svgEl('circle', { cx: 80, cy: 80, r: RADIUS, class: 'donut-track' }));
  let offset = 0;
  shown.forEach((item, i) => {
    const length = (item.value / total) * RING;
    const slice = svgEl('circle', {
      cx: 80, cy: 80, r: RADIUS, class: 'donut-slice',
      'stroke-dasharray': `${length} ${RING - length}`, 'stroke-dashoffset': -offset, transform: 'rotate(-90 80 80)',
    });
    slice.style.stroke = CHART_COLORS[i % CHART_COLORS.length]; // CSSOM: a var() works here, not in the attribute
    if (!item.other) for (const [key, value] of Object.entries(dataset(item))) slice.dataset[key] = value;
    const title = document.createElementNS(SVG_NS, 'title');
    title.textContent = `${item.label}: ${item.value}`;
    slice.appendChild(title);
    svg.appendChild(slice);
    offset += length;
  });
  const middle = svgEl('text', { x: 80, y: 86, 'text-anchor': 'middle', class: 'donut-total' });
  middle.textContent = String(total);
  svg.appendChild(middle);
  const legend = h('ul', { class: 'donut-legend' }, shown.map((item, i) => h('li',
    item.other ? null : { class: 'clickable', dataset: dataset(item) },
    h('span', { class: 'swatch', style: { background: CHART_COLORS[i % CHART_COLORS.length] } }),
    h('span', { class: 'l' }, item.label),
    h('span', { class: 'v' }, `${item.value} (${Math.round((item.value / total) * 100)}%)`))));
  return h('div', { class: 'donut' }, svg, legend);
}
