// "Saved — 03.12.2026 is outside the current date range." with a Show it button (see data.widenRangeTo).
import { inRange } from '../state.js';
import { h, setChildren } from '../dom.js';
import { $, dmy } from '../util.js';

/** After creating or re-dating a vessel: if the current range hides it, say so and offer "Show it". */
export function noticeIfOutsideRange(vessel) {
  if (!inRange(vessel.date)) showOutsideRange(vessel.date);
}

export function showOutsideRange(dateIso) {
  const box = $('#rangeNotice');
  setChildren(box, `Saved — ${dmy(dateIso)} is outside the current date range. `,
    h('button', { class: 'btn ghost small', dataset: { act: 'show-outside', date: dateIso } }, 'Show it'));
  box.hidden = false;
}

export function hideRangeNotice() {
  const box = $('#rangeNotice');
  if (!box) return;
  box.hidden = true;
  setChildren(box);
}
