// Read-only reports: one vessel's summary, and the combined summary of an OPR.
import {
  headEl, inProgressTagEl, metaBadgesEl, pillEl, portCallBlockEl, profitClass, serviceCountsEl, serviceStatusEl,
  statusChipEl, tagLabel,
} from '../components.js';
import { MULTI, NO_AGENT, can, serviceDetails } from '../config.js';
import { h, icon } from '../dom.js';
import { openModal } from '../modal.js';
import { api } from '../api.js';
import { ensureVessel } from '../data.js';
import { setStatus } from '../feedback.js';
import { filterParams, rememberVessels, state } from '../state.js';
import { dmy, fmt, sign } from '../util.js';

const txt = (x) => (x === null || x === undefined ? '' : String(x));
const teal = { color: 'var(--accent)' };
const pillsTight = (...pills) => h('div', { class: 'pills', style: { marginTop: '0' } }, pills);

function crewTable(list, group) {
  if (!list.length) return h('div', { class: 'none', style: { padding: '6px 0', fontSize: '12px' } }, 'None');
  const rows = list.map((member) => {
    const personal = member.personalStructured || {};
    const segments = (member.flightStructured && member.flightStructured.segments) || [];
    let flight = '—';
    if (segments.length) {
      const leg = group === 'off' ? segments[0] : segments[segments.length - 1];
      const [city, time] = group === 'off' ? [leg.departureCity, leg.departureTime] : [leg.arrivalCity, leg.arrivalTime];
      flight = `${(city || '').split(',')[0]} · ${time || ''}`;
    }
    return h('tr', null, h('td', null, member.name || '—'), h('td', { style: teal }, personal.rank || '—'),
      h('td', { class: 'none' }, personal.nationality || '—'), h('td', { style: teal }, flight));
  });
  return h('table', { class: 'crew-table' },
    h('tr', { class: 'none' }, h('th', null, 'Name'), h('th', null, 'Rank'), h('th', null, 'Nationality'),
      h('th', null, group === 'off' ? 'Departure' : 'Arrival')),
    rows);
}

// Typed amounts come only with money.edit, figures (profit, totals) only with money.view: show what was sent.
const seeMoney = () => can('money.view');
const editMoney = () => can('money.edit');

function multiEntryBlock(service) {
  const entries = service.data.entries || [];
  if (!entries.length) return h('div', { class: 'none' }, 'No entries.');
  const lines = entries.map((entry, i) => {
    const calc = (service.calc?.entries || [])[i] || {};
    const profit = calc.profit_egp || 0;
    return h('div', { class: 'entry-line' },
      h('div', { class: 't' }, `Entry ${i + 1}${entry.awb ? ` — AWB: ${entry.awb}` : ''}`),
      pillsTight(
        entry.weight ? pillEl('Weight', `${txt(entry.weight)} kg`) : null,
        entry.cost != null ? pillEl('Cost', `${txt(entry.costCurrency)} ${fmt(entry.cost)}`) : null,
        entry.revenue != null ? pillEl('Revenue', `${txt(entry.revenueCurrency)} ${fmt(entry.revenue)}`, 'good') : null,
        seeMoney() ? pillEl('Profit (EGP)', sign(profit), profitClass(profit)) : null));
  });
  return [lines, h('div', { class: 'pills' }, pillEl('Entries', entries.length),
    seeMoney() ? pillEl('Total profit (EGP)', sign(service.calc.profit_egp), profitClass(service.calc.profit_egp)) : null)];
}

// The service's own detail fields (SERVICE_FIELDS), one "Label: value" line each.
function detailLinesEl(service) {
  const details = serviceDetails(service.type, service.data);
  return details.length ? details.map(([label, value]) =>
    h('div', { class: 'none sum-detail' }, `${label}: `, h('b', { class: 'sum-detail-value' }, value))) : null;
}

function cashToMasterBlock(service) {
  const d = service.data;
  if (!editMoney() && !seeMoney()) return detailLinesEl(service);
  const share = d.shareMode === 'fixed' ? `${txt(d.amountCurrency)} ${fmt(d.fixedRevenue)}` : `${txt(d.percentage ?? 0)}%`;
  return [detailLinesEl(service), pillsTight(
    editMoney() ? [pillEl('Amount', `${txt(d.amountCurrency)} ${fmt(d.amount)}`), pillEl('Our share', share)] : null,
    seeMoney() ? [pillEl('Our revenue (EGP)', fmt(service.calc.revenue_egp), 'good'),
      pillEl('Paid to master (EGP)', fmt(service.calc.to_master_egp)),
      pillEl('Profit (EGP)', sign(service.calc.profit_egp), profitClass(service.calc.profit_egp))] : null,
    d.exchangeRate ? pillEl('Rate used', txt(d.exchangeRate)) : null)];
}

function singleBlock(service) {
  const d = service.data;
  const extraLine = detailLinesEl(service);
  if (!editMoney() && !seeMoney()) return extraLine;
  return [extraLine, pillsTight(
    editMoney() ? [pillEl('Cost', `${txt(d.costCurrency)} ${fmt(d.cost)}`), pillEl('Revenue', `${txt(d.revenueCurrency)} ${fmt(d.revenue)}`, 'good')] : null,
    seeMoney() ? pillEl('Profit (EGP)', sign(service.calc.profit_egp), profitClass(service.calc.profit_egp)) : null,
    d.exchangeRate ? pillEl('Rate used', txt(d.exchangeRate)) : null)];
}

// Any money on the service, judged from what this person was sent (figures, else the typed amounts).
const hasMoney = (service) => (service.calc
  ? service.calc.cost_egp || service.calc.revenue_egp
  : (service.data.cost ?? '') !== '' || (service.data.revenue ?? '') !== '');

function serviceBlock(service) {
  let inner;
  if (service.type === 'Others / Remarks') inner = [h('div', null, service.data.note || '—'), hasMoney(service) ? singleBlock(service) : null];
  else if (MULTI.includes(service.type)) inner = multiEntryBlock(service);
  else if (service.type === 'Cash to Master') inner = cashToMasterBlock(service);
  else inner = singleBlock(service);
  return h('div', { class: 'sum-block' }, h('h4', null, service.type, ' ', serviceStatusEl(service.status)), inner);
}

function crewBlock(service) {
  const on = service.data.onSigners || [];
  const off = service.data.offSigners || [];
  return h('div', { class: 'crew-box' },
    h('h4', { class: 'crew-title' }, icon('users'), ' Crew Change ', h('span', { class: 'tag' }, `${on.length} On`), ' ',
      h('span', { class: 'tag' }, `${off.length} Off`), ' ', serviceStatusEl(service.status)),
    h('div', { class: 'section-title', style: { marginTop: '10px', color: 'var(--success)' } }, 'On-signers'), crewTable(on, 'on'),
    h('div', { class: 'section-title', style: { color: 'var(--warning)' } }, 'Off-signers'), crewTable(off, 'off'),
    hasMoney(service) ? singleBlock(service) : null);
}

const sectionTitle = (label, style = null) => h('div', { class: 'section-title', style }, h('span', null, label));
const closeButton = () => h('button', { class: 'btn ghost', dataset: { act: 'close' } }, 'Close');

export async function openSummary(id) {
  const vessel = await ensureVessel(id);
  if (!vessel) return;
  state.ctx = { view: 'summary', vesselId: id };
  const services = vessel.services;
  const body = [
    services.length ? null : h('div', { class: 'hint' }, 'No services recorded.'),
    services.filter((s) => s.type !== 'Crew Change').map(serviceBlock),
    services.filter((s) => s.type === 'Crew Change').map(crewBlock),
    seeMoney() && services.some(hasMoney)
      ? h('div', { class: 'profit-banner' }, h('b', null, 'TOTAL PROFIT (EGP)'),
        h('span', { style: { color: `var(${vessel.total_profit_egp >= 0 ? '--success' : '--danger'})` } }, `${sign(vessel.total_profit_egp)} EGP`))
      : null,
  ];
  const summaryCards = [...(seeMoney() ? [['Total Cost LE', fmt(vessel.total_cost_egp)]] : []), ...Object.entries(vessel.summary || {})]
    .map(([key, value]) => h('div', { class: 'sum-card' }, h('span', null, key), h('b', null, value)));

  openModal(
    headEl(vessel.name, [...metaBadgesEl(vessel), statusChipEl(vessel.status)]),
    h('div', { class: 'm-body' },
      sectionTitle('Port call'), portCallBlockEl(vessel),
      sectionTitle('Services on this vessel', { marginTop: '20px' }),
      h('div', { style: { marginBottom: '14px' } }, serviceCountsEl(vessel), ' ', inProgressTagEl(vessel.services)),
      sectionTitle('Service details'), body,
      sectionTitle('Financial summary', { marginTop: '20px' }),
      h('div', { class: 'sum-grid' }, summaryCards)),
    h('div', { class: 'm-foot' }, h('span'), h('div', { class: 'right' },
      h('button', { class: 'btn ghost', dataset: { act: 'print' } }, icon('printer'), ' Print'), ' ',
      h('button', { class: 'btn ghost', dataset: { act: 'open-vessel', id: vessel.id } }, 'Open details'), ' ',
      closeButton())),
  );
}

const OPR_SUMMARY_LIMIT = 200;

/** Under the Dashboard's agent / service filters: the vessels with a counted job, each with its counted services
 * only (the same rule as the server's OPR cards, sheet/dashboard.py). Without them the list is unchanged. */
function dashboardFiltered(vessels) {
  const { agent, service } = state.dashboardFilter;
  if (!agent && !service) return vessels;
  const who = agent === NO_AGENT ? '' : agent;
  const counted = (s) => (!service || s.type === service) && (!agent || s.agent === who);
  const portCall = (v) => !service && agent && (v.arrival_agent === who || v.sailing_agent === who);
  return vessels
    .map((v) => {
      const services = v.services.filter(counted);
      const cost = services.reduce((n, s) => n + (s.calc?.cost_egp ?? 0), 0);
      return { ...v, services, total_cost_egp: Math.round(cost * 100) / 100, keep: services.length > 0 || portCall(v) };
    })
    .filter((v) => v.keep);
}

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
  rememberVessels(list.vessels);
  const vessels = dashboardFiltered(list.vessels);
  const counts = figures.service_counts;
  state.ctx = { view: 'opr-summary', vesselId: null };

  const perVessel = vessels.map((v) => h('div', { class: 'svc-card clickable', dataset: { act: 'summary', id: v.id } },
    h('div', { class: 'svc-top' }, h('strong', null, v.name),
      h('span', { class: 'none', style: { fontSize: '12px' } }, `${dmy(v.date)} · `,
        seeMoney() ? h('span', { class: 'num' }, v.total_cost_egp ? `LE ${fmt(v.total_cost_egp)}` : '—') : null)),
    h('div', { style: { marginTop: '8px' } }, v.services.length
      ? v.services.map((s) => h('span', { class: 'svc-chip' }, tagLabel(s)))
      : h('span', { class: 'none' }, h('i', null, 'No services')))));
  const countPills = Object.entries(counts).map(([k, n]) => pillEl(k, n, 'good'));

  openModal(
    headEl(`${opr} — Services summary`, `${figures.vessels} vessels · ${figures.services} services`
      + (figures.cost_egp === undefined ? '' : ` · LE ${fmt(figures.cost_egp)}`)),
    h('div', { class: 'm-body' },
      list.count > list.vessels.length ? h('div', { class: 'hint' }, `Showing the first ${list.vessels.length} of ${list.count} vessels.`) : null,
      sectionTitle('All services (combined)'),
      h('div', { class: 'pills', style: { marginBottom: '22px' } }, countPills.length ? countPills : h('span', { class: 'none' }, 'None')),
      sectionTitle('Per vessel breakdown'), perVessel),
    h('div', { class: 'm-foot' }, h('span'), h('div', { class: 'right' }, closeButton())),
  );
}
