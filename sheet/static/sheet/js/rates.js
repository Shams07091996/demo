// Agreed rates fill in a service's revenue (pure: unit-tested in tools/parsing_test.js). The rate is the billing
// party's for that service type; what it means depends on the type (`units`, constants.RATE_UNITS on the server):
// per service, per unit of quantity (Fresh Water), per line (Parcels / Courier / Landing), or a percentage (Cash to
// Master). A box the person typed in during this dialog (`touched`) is never filled; on a saved service only an
// empty or 0 value is filled, so a typed revenue stays. On a new service, a switch to a payer with no rate clears
// what the `previous` rate filled (never a box typed in). The server stores whatever is sent.

const cents = (value) => Math.round(value * 100) / 100; // to the cent, as finance.money does on the server
const isEmpty = (value) => value === null || value === undefined || value === '' || Number(value) === 0;

/** The customer's agreed rate for this type: {amount, currency, unit}, or null. */
export function rateFor(customer, serviceType, units) {
  const unit = units[serviceType];
  const rate = customer?.rates?.[serviceType];
  if (!unit || !rate) return null;
  return { amount: Number(rate.amount), currency: rate.currency || 'USD', unit };
}

/** A copy of `data` with the revenue filled from `rate` where allowed. */
export function fillRevenue({ rate, previous = null, data, isNew, touched }) {
  const out = { ...data, entries: data.entries ? data.entries.map((e) => ({ ...e })) : undefined };
  if (!data.entries) delete out.entries;
  if (!rate) return previous && isNew ? clearFilled(previous.unit, out, touched) : out;
  const may = (key, value) => !touched.has(key) && (isNew || isEmpty(value));
  if (rate.unit === 'service' && may('revenue', data.revenue)) {
    out.revenue = rate.amount;
    out.revenueCurrency = rate.currency;
  } else if (rate.unit === 'unit' && may('revenue', data.revenue)) {
    const quantity = Number(data.quantity);
    if (data.quantity === '' || data.quantity === null || data.quantity === undefined || !Number.isFinite(quantity)) return out;
    out.revenue = cents(rate.amount * quantity);
    out.revenueCurrency = rate.currency;
  } else if (rate.unit === 'line' && out.entries) {
    out.entries.forEach((entry, i) => {
      if (!may(`entry:${i}`, entry.revenue)) return;
      entry.revenue = rate.amount;
      entry.revenueCurrency = rate.currency;
    });
  } else if (rate.unit === 'percent' && data.shareMode !== 'fixed' && may('percentage', data.percentage)) {
    out.percentage = rate.amount;
  }
  return out;
}

/** Empty the boxes a rate of this unit fills, except the ones typed in. */
function clearFilled(unit, out, touched) {
  if ((unit === 'service' || unit === 'unit') && !touched.has('revenue')) out.revenue = '';
  else if (unit === 'line' && out.entries) out.entries.forEach((entry, i) => { if (!touched.has(`entry:${i}`)) entry.revenue = ''; });
  else if (unit === 'percent' && !touched.has('percentage')) out.percentage = '';
  return out;
}
