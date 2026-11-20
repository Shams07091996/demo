// The master receipt of a service: a form pre-filled by the server, edited, then downloaded as a PDF (nothing saved).
import { api, download } from '../api.js';
import { headEl } from '../components.js';
import { showError } from '../feedback.js';
import { h } from '../dom.js';
import { openModal } from '../modal.js';
import { getVessel, state } from '../state.js';
import { $, formValues } from '../util.js';

const field = (label, control) => h('div', { class: 'field' }, h('label', null, label), control);
const url = (serviceId) => `/api/services/${serviceId}/receipt/`;

export async function openReceipt(serviceId) {
  const { vesselId } = state.ctx;
  let receipt;
  try {
    ({ receipt } = await api(url(serviceId)));
  } catch (error) {
    showError(error.message);
    return;
  }
  state.ctx = { view: 'receipt', vesselId, serviceId };
  openModal(
    headEl('Receipt', getVessel(vesselId)?.name || receipt.vessel),
    h('div', { class: 'm-body', id: 'receipt-form' },
      h('div', { class: 'row two' },
        field('Port', h('input', { attrs: { name: 'port' }, value: receipt.port })),
        field('Date', h('input', { attrs: { name: 'date' }, value: receipt.date }))),
      field('Vessel', h('input', { attrs: { name: 'vessel' }, value: receipt.vessel })),
      field('Services', h('textarea', { attrs: { name: 'services', rows: 6 }, value: receipt.services }))),
    h('div', { class: 'm-foot' },
      h('button', { class: 'btn ghost', dataset: { act: 'back' } }, 'Cancel'),
      h('div', { class: 'right' }, h('button', { class: 'btn primary', dataset: { act: 'receipt-download' } }, 'Download'))),
  );
}

export async function downloadReceipt() {
  const error = await download(url(state.ctx.serviceId), 'Could not make the receipt.', formValues($('#receipt-form')));
  if (error) showError(error);
}
