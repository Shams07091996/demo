// Read-only configuration: what the server rendered into the page, plus fixed UI constants.
import { $ } from './util.js';

const readJson = (id) => JSON.parse(document.getElementById(id).textContent);

export const ME = readJson('me-data');
export const PORTS = readJson('ports-data');
export const TYPES = readJson('types-data');
export const SUMMARY_FIELDS = readJson('summary-fields-data');
export const OPTION_KINDS = readJson('option-kinds-data');   // [{key, label}] OPR / POC / Agent
export const TIME_FIELDS = readJson('time-fields-data');      // [{key, label}] arrival … sailing

export const PDF = { lib: document.body.dataset.pdfLib, worker: document.body.dataset.pdfWorker };

export const PORT_LABEL = Object.fromEntries(PORTS.map((p) => [p.key, p.label]));
export const PORT_COLOR = { alexandria: 'var(--teal)', portsaid: 'var(--gold)', damietta: '#a8dadc', suez: '#c77dff' };

// Service kinds (must match sheet/constants.py).
export const MULTI = ['Delivery Parcels', 'Delivery Courier', 'Landing'];
export const NO_MONEY = ['Crew Change', 'Others / Remarks'];
export const SINGLE_EXTRA = {
  'Medical Treatment': { name: 'patientName', label: 'Patient name', type: 'text' },
  Certificates: { name: 'certName', label: 'Certificate name', type: 'text' },
  'Fresh Water': { name: 'quantity', label: 'Quantity (tons)', type: 'number' },
};

export const STATUS_LABEL = {
  scheduled: 'Scheduled',
  arrived: 'Arrived',
  berthed: 'Berthed',
  operating: 'Operating',
  ops_finished: 'Ops finished',
  sailed: 'Sailed',
};

export const CHART_COLORS = [
  '#00b4d8', '#f4a261', '#52b788', '#e63946', '#a8dadc', '#9b5de5', '#f15bb5', '#fee440',
  '#00bbf9', '#fb5607', '#ff006e', '#8338ec', '#3a86ff', '#06d6a0', '#ffd166',
];

export const el = {
  overlay: $('#overlay'),
  modal: $('#modal'),
};
