// One agent's jobs under the Dashboard's filters (clicked from the jobs-per-agent chart or table).
import { api } from '../api.js';
import { headEl } from '../components.js';
import { NO_AGENT } from '../config.js';
import { h } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openModal } from '../modal.js';
import { dashboardParams, state } from '../state.js';
import { dmy } from '../util.js';

/** `agent` is an agent name, or NO_AGENT for the jobs nobody was assigned to. */
export async function openAgentJobs(agent) {
  let data;
  try {
    data = await api(`/api/dashboard/jobs/?${dashboardParams({ agent })}`);
  } catch (error) {
    setStatus('error', error.message);
    return;
  }
  state.ctx = { view: 'agent-jobs', vesselId: null };
  const { jobs, truncated } = data;
  const rows = jobs.map((job) => h('tr', { class: 'clickable', dataset: { act: 'open-vessel', id: job.vessel_id } },
    h('td', null, job.vessel), h('td', null, dmy(job.date)), h('td', null, job.job)));
  openModal(
    headEl(agent === NO_AGENT ? '(no agent)' : agent, `${jobs.length}${truncated ? '+' : ''} jobs`),
    h('div', { class: 'm-body' },
      truncated ? h('div', { class: 'hint' }, `Showing the newest ${jobs.length}.`) : null,
      jobs.length
        ? h('table', { class: 'fig-table' },
          h('thead', null, h('tr', null, h('th', null, 'Vessel'), h('th', null, 'Date'), h('th', null, 'Job'))),
          h('tbody', null, rows))
        : h('div', { class: 'none' }, 'No jobs.')),
    h('div', { class: 'm-foot' }, h('span'), h('div', { class: 'right' },
      h('button', { class: 'btn ghost', dataset: { act: 'close' } }, 'Close'))),
  );
}
