// The edit-conflict warning: a save refused because someone saved the same record after this dialog opened (409).
// The panel says who, when and which fields; the typed values stay in the dialog until the person chooses.
import { h } from './dom.js';
import { $ } from './util.js';

let pending = null; // { reload, force } of the panel on screen

/** The two lines of the warning, from the server's `conflict` ({who, same_person, at, fields, version}). */
export function conflictLines(conflict, noun) {
  const fields = (conflict.fields || []).join(', ');
  return conflict.same_person
    ? [`You changed this ${noun} at ${conflict.at} in another window.`, `Changed: ${fields}. Nothing of yours was saved.`]
    : [`${conflict.who} changed this ${noun} at ${conflict.at} while you had it open.`,
      `They changed: ${fields}. Nothing of yours was saved.`];
}

export function clearConflict() {
  $('#conflict-panel')?.remove();
  pending = null;
}

/**
 * Show the warning at the top of the open dialog. `reload()` reopens the dialog from the server; `force(version)`
 * sends the same save again with the version the server has now (a further save meanwhile warns again).
 */
export function showConflict(conflict, noun, { reload, force }) {
  clearConflict();
  const body = $('#modal .m-body');
  if (!body) return;
  $('#modal .error')?.remove(); // an older error box would only confuse
  const [first, second] = conflictLines(conflict, noun);
  const panel = h('div', { class: 'conflict', id: 'conflict-panel', attrs: { role: 'alert' } },
    h('p', null, first), h('p', null, second),
    h('div', { class: 'conflict-actions' },
      h('button', { class: 'btn ghost small', attrs: { type: 'button' }, dataset: { act: 'conflict-reload' } }, 'Show their version'),
      h('button', { class: 'btn primary small', attrs: { type: 'button' }, dataset: { act: 'conflict-force' } }, 'Save mine anyway')));
  body.prepend(panel);
  panel.scrollIntoView({ block: 'nearest' });
  pending = { reload, force: () => force(conflict.version) };
}

/** The panel's buttons: 'reload' or 'force'. */
export function conflictAction(name) {
  const chosen = pending;
  clearConflict();
  if (!chosen) return undefined;
  return name === 'reload' ? chosen.reload() : chosen.force();
}
