// Under a list: "Showing x–y of n …", rows per page, Prev / Page p of n / Next.
// Used by the Vessels page and by the Hotels / Transport pages.
import { PAGE_SIZES, state } from '../state.js';
import { $ } from '../util.js';

/**
 * @param o {count, pages, page, size, noun, sizeId, prev, next} — `prev` / `next` are the data-act attributes
 *          (with any extra data-* attributes) of the Prev / Next buttons.
 */
export function pagerHtml({ count, pages, page, size, noun, sizeId, prev, next }) {
  const first = count ? (page - 1) * size + 1 : 0;
  const last = Math.min(count, page * size);
  const sizes = PAGE_SIZES.map((n) => `<option value="${n}" ${n === size ? 'selected' : ''}>${n}</option>`).join('');
  const nav = pages > 1
    ? `<button class="btn ghost small" ${prev} ${page <= 1 ? 'disabled' : ''}>‹ Prev</button>
       <span class="pager-pos">Page ${page} of ${pages}</span>
       <button class="btn ghost small" ${next} ${page >= pages ? 'disabled' : ''}>Next ›</button>`
    : '';
  return `<span class="pager-count">Showing <strong>${first}–${last}</strong> of <strong>${count}</strong> ${noun}</span>
    <span class="pager-nav"><label class="pager-size">Rows per page
      <select id="${sizeId}" class="select">${sizes}</select></label>${nav}</span>`;
}

export function renderPager() {
  const { count, pages, page } = state.list;
  $('#pager').innerHTML = pagerHtml({
    count, pages, page, size: state.filter.pageSize, noun: 'vessels', sizeId: 'page-size',
    prev: 'data-act="page-prev"', next: 'data-act="page-next"',
  });
}
