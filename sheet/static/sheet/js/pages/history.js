// The History page (admins only): every create / change / delete with who, when, from where and old → new,
// newest first. Read from /api/history/; nothing on this page can change the history.
import { api } from '../api.js';
import { PORT_LABEL } from '../config.js';
import { h, optionEls, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { pagerEl } from '../render/pager.js';
import { $ } from '../util.js';

const TYPES = [
  ['', 'Everything'], ['vessel', 'Vessel'], ['service', 'Service'], ['hotelstay', 'Hotel stay'],
  ['transfer', 'Transfer'], ['guest', 'Guest'], ['option', 'Master data'], ['exchangerate', 'Exchange rate'], ['disposalprice', 'Garbage & Sludge price'], ['vesseldisposal', 'Garbage & Sludge quantities'],
  ['profile', 'User role'], ['user', 'User account'],
];
const TYPE_LABEL = Object.fromEntries(TYPES);
const ACTION_LABEL = { create: 'Created', update: 'Changed', delete: 'Deleted', letter: 'LOG made for', receipt: 'Receipt made for' };
const MAX_VALUE = 200;
const INPUT_DELAY_MS = 400;

const filter = { from: '', to: '', type: '', user: '', page: 1, pageSize: 25 };
let data = { records: [], count: 0, pages: 1, page: 1 };
let ticket = 0;
let wired = false;

function valueText(value) {
  if (value === null || value === undefined || value === '') return '—';
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  return text.length > MAX_VALUE ? `${text.slice(0, MAX_VALUE)}…` : text;
}

function changeLines(record) {
  return Object.entries(record.changes).map(([field, [before, after]]) => {
    let text;
    if (['create', 'letter', 'receipt'].includes(record.action)) text = valueText(after);
    else if (record.action === 'delete') text = valueText(before);
    else text = `${valueText(before)} → ${valueText(after)}`;
    return h('div', null, h('strong', null, field), ': ', text);
  });
}

function when(iso) {
  const [day, time] = iso.split('T');
  return `${day.split('-').reverse().join('.')} ${time.slice(0, 8)}`;
}

function rowEl(record) {
  const what = `${ACTION_LABEL[record.action] || record.action} ${TYPE_LABEL[record.object_type] || record.object_type}`;
  return h('tr', null,
    h('td', null, when(record.at)),
    h('td', null, record.username),
    h('td', null, `${what} #${record.object_id}`),
    h('td', null, record.port ? PORT_LABEL[record.port] || record.port : 'All'),
    h('td', null, changeLines(record)),
    h('td', null, record.ip || '—'));
}

function render() {
  setChildren($('#hi-tbody'), data.records.map(rowEl));
  $('#hi-empty').hidden = data.records.length > 0;
  setChildren($('#hi-pager'), pagerEl({
    count: data.count, pages: data.pages, page: data.page, size: filter.pageSize, noun: 'changes', sizeId: 'hi-page-size',
    prev: { act: 'history-page', step: -1 }, next: { act: 'history-page', step: 1 },
  }));
}

function params() {
  const values = {
    from: filter.from, to: filter.to, type: filter.type, user: filter.user, page: filter.page, page_size: filter.pageSize,
  };
  return new URLSearchParams(Object.entries(values).filter(([, v]) => v !== '' && v !== null && v !== undefined));
}

async function load() {
  wire();
  const mine = ++ticket;
  let answer;
  try {
    answer = await api(`/api/history/?${params()}`);
  } catch (error) {
    if (mine === ticket) setStatus('error', error.message);
    return;
  }
  if (mine !== ticket) return; // a newer request is on its way
  data = answer;
  filter.page = answer.page;
  render();
}

function setFilter(patch) {
  Object.assign(filter, patch);
  if (!('page' in patch)) filter.page = 1;
  return load();
}

/** Hook up the page's controls once, the first time it is shown. */
function wire() {
  if (wired) return;
  wired = true;
  setChildren($('#hi-type'), optionEls(TYPES, filter.type));
  $('#hi-type').addEventListener('change', (event) => setFilter({ type: event.target.value }));
  let timer;
  const later = (read) => () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      const patch = read();
      if (patch) setFilter(patch);
    }, INPUT_DELAY_MS);
  };
  const onDate = later(() => {
    const from = $('#hi-from').value;
    const to = $('#hi-to').value;
    if (from && to && from > to) {
      setStatus('error', 'From must be on or before To.');
      return null;
    }
    return from !== filter.from || to !== filter.to ? { from, to } : null;
  });
  $('#hi-from').addEventListener('change', onDate);
  $('#hi-to').addEventListener('change', onDate);
  $('#hi-user').addEventListener('input', later(() => {
    const user = $('#hi-user').value.trim();
    return user !== filter.user ? { user } : null;
  }));
  $('#hi-pager').addEventListener('change', (event) => {
    if (event.target.id === 'hi-page-size') setFilter({ pageSize: Number(event.target.value) });
  });
}

export const historyPage = {
  load,
  step: (n) => setFilter({ page: Math.min(Math.max(1, filter.page + n), data.pages) }),
};
