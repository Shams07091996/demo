// Exchange rates page.
import { ME } from '../config.js';
import { state } from '../state.js';
import { $, localISO } from '../util.js';

export function renderRatesPage() {
  const chips = state.rates.map((r) =>
    `<span class="rate-chip">${r.label} <b>${r.rate}</b>${ME.isAdmin ? `<button data-act="del-rate" data-id="${r.id}" title="Delete">✕</button>` : ''}</span>`);
  // Rates are shared by every port, so only admins may change them (the server enforces this too).
  const form = ME.isAdmin
    ? `<div class="section-title" style="margin-top:18px"><span>Add or update a rate</span></div>
       <div class="row three" id="rate-form" style="max-width:640px;align-items:end">
         <div class="field"><label>Month</label><input type="month" name="month" value="${localISO().slice(0, 7)}"></div>
         <div class="field"><label>Rate (EGP per USD)</label><input type="number" step="any" min="0" name="rate" placeholder="e.g. 50.25"></div>
         <div class="field"><button class="btn primary" data-act="save-rate">Save rate</button></div></div>`
    : ME.canEdit ? '<p class="help">Exchange rates are shared by every port; ask an admin to add or change one.</p>' : '';
  $('#rates-panel').innerHTML = (chips.join('') || '<div class="none">No rates set yet.</div>') + form;
}
