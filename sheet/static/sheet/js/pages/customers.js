// The Customers page: who we bill, with contacts, agreed rates and linked ships. Everyone reads it (a row opens the
// customer, read-only for non-admins); only admins add and change customers.
import { h, setChildren } from '../dom.js';
import { setStatus } from '../feedback.js';
import { openCustomerDialog } from '../modals/customer.js';
import { customers, loadCustomers } from '../parties.js';
import { $ } from '../util.js';

function render() {
  const list = customers();
  setChildren($('#cu-head'), h('tr', null, ['Name', 'Contacts', 'Agreed rates', 'Ships'].map((t) => h('th', null, t))));
  setChildren($('#cu-tbody'), list.map((c) => h('tr', { class: c.active ? 'clickable' : 'clickable inactive', dataset: { act: 'customer-open', id: c.id } },
    h('td', null, c.name), h('td', null, String(c.contacts.length)), h('td', null, String(Object.keys(c.rates).length)),
    h('td', null, String(c.ships.length)))));
  $('#cu-empty').hidden = list.length > 0;
}

export const customersPage = {
  async load() {
    try {
      await loadCustomers(true);
      render();
    } catch (error) {
      setStatus('error', error.message);
    }
  },
  open(id) {
    const customer = id ? customers().find((c) => c.id === id) : null;
    openCustomerDialog(customer, () => customersPage.load());
  },
};
