// Read-only configuration: what the server rendered into the page, plus fixed UI constants.
import { $ } from './util.js';

const readJson = (id) => JSON.parse(document.getElementById(id).textContent);

export const ME = readJson('me-data');
export const PORTS = readJson('ports-data');
export const TYPES = readJson('types-data');
export const RATE_UNITS = readJson('rate-units-data'); // {service type: service | unit | line | percent}
export const SUMMARY_FIELDS = readJson('summary-fields-data');
export const OPTION_KINDS = readJson('option-kinds-data');   // [{key, label}] OPR / POC / Agent
export const TIME_FIELDS = readJson('time-fields-data');      // [{key, label}] arrival … sailing
export const NO_AGENT = readJson('no-agent-data');            // Dashboard agent filter: jobs with no agent


export const PORT_LABEL = Object.fromEntries(PORTS.map((p) => [p.key, p.label]));

// What this person may do and which pages they have (the server's lists as they apply; Admins: everything). The
// screens only hide what the server would refuse anyway.
export const can = (key) => ME.permissions.includes(key);
export const sees = (page) => ME.pages.includes(page);

// The ports this person works in (Admins: every port), in page order: the port filters. Functions, because the
// Ports page changes PORTS in place.
export const myPorts = () => PORTS.filter((p) => ME.isAdmin || ME.ports.includes(p.key));
// Where a new record can go: their ports that are turned on.
export const openPorts = () => myPorts().filter((p) => p.active);

// Service kinds (must match sheet/constants.py).
export const MULTI = ['Delivery Parcels', 'Delivery Courier', 'Landing'];
export const SINGLE_EXTRA = {
  'Medical Treatment': { name: 'patientName', label: 'Patient name', type: 'text' },
  Certificates: { name: 'certName', label: 'Certificate name', type: 'text' },
  'Fresh Water': { name: 'quantity', label: 'Quantity (tons)', type: 'number' },
};

// Operations status of a service (sheet/constants.py SERVICE_STATUSES) and its label colour (app.css).
export const BILLING = { account: 'On account', cash: 'Cash' }; // constants.BILLING
export const SERVICE_STATUS = { in_progress: 'In progress', completed: 'Completed', cancelled: 'Cancelled' };
export const SERVICE_STATUS_CLASS = { in_progress: 'st-progress', completed: 'st-done', cancelled: 'st-cancel' };

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
  'var(--c11)', 'var(--c12)', 'var(--c13)', 'var(--c14)',
];

export const el = {
  overlay: $('#overlay'),
  modal: $('#modal'),
};
