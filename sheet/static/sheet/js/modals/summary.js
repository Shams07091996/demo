// Read-only reports: one vessel's summary, and the combined summary of an OPR.
import { head, metaBadges, pill, portCallBlock, profitClass, serviceCounts, statusChip, tagLabel } from '../components.js';
import { MULTI, NO_MONEY, SINGLE_EXTRA } from '../config.js';
import { openModal } from '../modal.js';
import { api } from '../api.js';
import { ensureVessel } from '../data.js';
import { setStatus } from '../feedback.js';
import { filterParams, rememberVessels, state } from '../state.js';
import { dmy, esc, fmt, sign, val } from '../util.js';

function crewTable(list, group) {
  if (!list.length) return '<div class="none" style="padding:6px 0;font-size:12px">None</div>';
  const rows = list.map((member) => {
    const personal = member.personalStructured || {};
    const segments = (member.flightStructured && member.flightStructured.segments) || [];
    let flight = '—';
    if (segments.length) {
      const leg = group === 'off' ? segments[0] : segments[segments.length - 1];
      const [city, time] = group === 'off' ? [leg.departureCity, leg.departureTime] : [leg.arrivalCity, leg.arrivalTime];
      flight = `${(city || '').split(',')[0]} · ${time || ''}`;
    }
    return `<tr><td>${esc(member.name || '—')}</td><td style="color:var(--teal)">${esc(personal.rank || '—')}</td>
      <td class="none">${esc(personal.nationality || '—')}</td><td style="color:var(--teal)">${esc(flight)}</td></tr>`;
  });
  return `<table class="crew-table"><tr class="none"><th>Name</th><th>Rank</th><th>Nationality</th>
    <th>${group === 'off' ? 'Departure' : 'Arrival'}</th></tr>${rows.join('')}</table>`;
}

function multiEntryBlock(service) {
  const entries = service.data.entries || [];
  if (!entries.length) return '<div class="none">No entries.</div>';
  const lines = entries.map((entry, i) => {
    const calc = (service.calc.entries || [])[i] || {};
    const profit = calc.profit_egp || 0;
    return `<div class="entry-line">
      <div class="t">Entry ${i + 1}${entry.awb ? ` — AWB: ${esc(entry.awb)}` : ''}</div>
      <div class="pills" style="margin-top:0">
        ${entry.weight ? pill('Weight', `${val(entry.weight)} kg`) : ''}
        ${entry.cost != null ? pill('Cost', `${val(entry.costCurrency)} ${fmt(entry.cost)}`) : ''}
        ${entry.revenue != null ? pill('Revenue', `${val(entry.revenueCurrency)} ${fmt(entry.revenue)}`, 'good') : ''}
        ${pill('Profit (EGP)', sign(profit), profitClass(profit))}</div></div>`;
  });
  return `${lines.join('')}<div class="pills">${pill('Entries', entries.length)}
    ${pill('Total profit (EGP)', sign(service.calc.profit_egp), profitClass(service.calc.profit_egp))}</div>`;
}

function cashToMasterBlock(service) {
  const d = service.data;
  const share = d.shareMode === 'fixed' ? `${val(d.amountCurrency)} ${fmt(d.fixedRevenue)}` : `${val(d.percentage ?? 0)}%`;
  return `<div class="pills" style="margin-top:0">
    ${pill('Amount', `${val(d.amountCurrency)} ${fmt(d.amount)}`)}${pill('Our share', share)}
    ${pill('Our revenue (EGP)', fmt(service.calc.revenue_egp), 'good')}
    ${pill('Paid to master (EGP)', fmt(service.calc.to_master_egp))}
    ${pill('Profit (EGP)', sign(service.calc.profit_egp), profitClass(service.calc.profit_egp))}
    ${d.exchangeRate ? pill('Rate used', val(d.exchangeRate)) : ''}</div>`;
}

function singleBlock(service) {
  const d = service.data;
  const extra = SINGLE_EXTRA[service.type];
  const extraLine = extra && d[extra.name]
    ? `<div class="none" style="margin-bottom:6px">${extra.label}: <b style="color:var(--white)">${esc(d[extra.name])}</b></div>`
    : '';
  return `${extraLine}<div class="pills" style="margin-top:0">
    ${pill('Cost', `${val(d.costCurrency)} ${fmt(d.cost)}`)}${pill('Revenue', `${val(d.revenueCurrency)} ${fmt(d.revenue)}`, 'good')}
    ${pill('Profit (EGP)', sign(service.calc.profit_egp), profitClass(service.calc.profit_egp))}
    ${d.exchangeRate ? pill('Rate used', val(d.exchangeRate)) : ''}</div>`;
}

function serviceBlock(service) {
  let inner;
  if (service.type === 'Others / Remarks') inner = `<div>${esc(service.data.note || '—')}</div>`;
  else if (MULTI.includes(service.type)) inner = multiEntryBlock(service);
  else if (service.type === 'Cash to Master') inner = cashToMasterBlock(service);
  else inner = singleBlock(service);
  return `<div class="sum-block"><h4>⚙ ${esc(service.type)}</h4>${inner}</div>`;
}

function crewBlock(service) {
  const on = service.data.onSigners || [];
  const off = service.data.offSigners || [];
  return `<div class="crew-box">
    <h4 class="crew-title">👥 Crew Change <span class="tag">↑ ${on.length} On</span> <span class="tag">↓ ${off.length} Off</span></h4>
    <div class="section-title" style="margin-top:10px;color:var(--success)">↑ On-signers</div>${crewTable(on, 'on')}
    <div class="section-title" style="color:var(--gold)">↓ Off-signers</div>${crewTable(off, 'off')}</div>`;
}

export async function openSummary(id) {
  const vessel = await ensureVessel(id);
  if (!vessel) return;
  state.ctx = { view: 'summary', vesselId: id };
  const services = vessel.services;
  const hasMoney = services.some((s) => !NO_MONEY.includes(s.type));
  const body =
    (services.length ? '' : '<div class="hint">No services recorded.</div>') +
    services.filter((s) => s.type !== 'Crew Change').map(serviceBlock).join('') +
    services.filter((s) => s.type === 'Crew Change').map(crewBlock).join('') +
    (hasMoney
      ? `<div class="profit-banner"><b>TOTAL PROFIT (EGP)</b>
         <span style="color:var(${vessel.total_profit_egp >= 0 ? '--success' : '--danger'})">${sign(vessel.total_profit_egp)} EGP</span></div>`
      : '');
  const summaryCards = [['Total Cost LE', fmt(vessel.total_cost_egp)], ...Object.entries(vessel.summary || {})]
    .map(([key, value]) => `<div class="sum-card"><span>${esc(key)}</span><b>${esc(value)}</b></div>`).join('');

  openModal(`${head(vessel.name, metaBadges(vessel) + statusChip(vessel.status))}
    <div class="m-body">
      <div class="section-title"><span>🕒 Port call</span></div>${portCallBlock(vessel)}
      <div class="section-title" style="margin-top:20px"><span>📋 Services on this vessel</span></div>
      <div style="margin-bottom:14px">${serviceCounts(vessel)}</div>
      <div class="section-title"><span>⚙ Service details</span></div>${body}
      <div class="section-title" style="margin-top:20px"><span>💰 Financial summary</span></div>
      <div class="sum-grid">${summaryCards}</div>
    </div>
    <div class="m-foot"><span></span><div class="right">
      <button class="btn ghost" data-act="print">🖨 Print</button>
      <button class="btn ghost" data-act="open-vessel" data-id="${vessel.id}">Open details</button>
      <button class="btn ghost" data-act="close">Close</button></div></div>`);
}

const OPR_SUMMARY_LIMIT = 200;

/** Combined summary of one OPR for the current date range and port (figures from the server). */
export async function openOprSummary(opr) {
  const figures = state.dashboard.oprs.find((o) => o.opr === opr);
  if (!figures) return;
  let list;
  try {
    const params = filterParams({ opr, page: 1, page_size: OPR_SUMMARY_LIMIT, q: '', bucket: '', sort: 'date', dir: 'desc' });
    list = await api(`/api/vessels/?${params}`);
  } catch (error) {
    setStatus('error', error.message);
    return;
  }
  const vessels = list.vessels;
  rememberVessels(vessels);
  const counts = figures.service_counts;
  const totalCost = figures.cost_egp;
  const serviceCount = figures.services;
  const capped = list.count > vessels.length
    ? `<div class="hint">Showing the first ${vessels.length} of ${list.count} vessels.</div>` : '';
  state.ctx = { view: 'opr-summary', vesselId: null };

  const perVessel = vessels.map((v) => `
    <div class="svc-card clickable" data-act="summary" data-id="${v.id}">
      <div class="svc-top"><strong>${esc(v.name)}</strong>
        <span class="none" style="font-size:12px">${dmy(v.date)} · <span class="num">${v.total_cost_egp ? `LE ${fmt(v.total_cost_egp)}` : '—'}</span></span></div>
      <div style="margin-top:8px">${v.services.length
        ? v.services.map((s) => `<span class="svc-chip">${esc(tagLabel(s))}</span>`).join('')
        : '<span class="none"><i>No services</i></span>'}</div></div>`).join('');

  openModal(`${head(`📋 ${opr} — Services summary`, `${figures.vessels} vessels · ${serviceCount} services · LE ${fmt(totalCost)}`)}
    <div class="m-body">${capped}
      <div class="section-title"><span>⚙ All services (combined)</span></div>
      <div class="pills" style="margin-bottom:22px">${Object.entries(counts).map(([k, n]) => pill(esc(k), n, 'good')).join('') || '<span class="none">None</span>'}</div>
      <div class="section-title"><span>🚢 Per vessel breakdown</span></div>${perVessel}
    </div>
    <div class="m-foot"><span></span><div class="right"><button class="btn ghost" data-act="close">Close</button></div></div>`);
}
