// Read-only configuration: what the server rendered into the page, plus fixed UI constants.
import { $ } from './util.js';

const readJson = (id) => JSON.parse(document.getElementById(id).textContent);

export const ME = readJson('me-data');
export const PORTS = readJson('ports-data');
export const TYPES = readJson('types-data');
export const SUMMARY_FIELDS = readJson('summary-fields-data');
export const OPTION_KINDS = readJson('option-kinds-data');   // [{key, label}] OPR / POC / Agent
export const TIME_FIELDS = readJson('time-fields-data');      // [{key, label}] arrival … sailing
export const NO_AGENT = readJson('no-agent-data');            // Dashboard agent filter: jobs with no agent


export const PORT_LABEL = Object.fromEntries(PORTS.map((p) => [p.key, p.label]));
export const PORT_COLOR = { alexandria: 'var(--c1)', portsaid: 'var(--c2)', damietta: 'var(--c3)', suez: 'var(--c5)' };

// Service kinds (must match sheet/constants.py).
export const MULTI = ['Delivery Parcels', 'Delivery Courier', 'Landing'];
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

// One colour per series, per mode (app.css --c1 … --c10): at least one per service type.
export const CHART_COLORS = [
  'var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)',
  'var(--c6)', 'var(--c7)', 'var(--c8)', 'var(--c9)', 'var(--c10)',
];

export const el = {
  overlay: $('#overlay'),
  modal: $('#modal'),
};
