// Live profit preview while a service form is open. The server recalculates on save and is the source of truth.
// Keep this in step with sheet/finance.py.
import { MULTI } from './config.js';
import { num } from './util.js';

export function calcLocal(type, data, monthRate) {
  const rate = num(data.exchangeRate) || num(monthRate);
  let rateMissing = false;
  const toEgp = (amount, currency) => {
    const value = num(amount);
    if (currency !== 'USD') return value;
    if (value && !rate) rateMissing = true;
    return value * (rate || 1);
  };

  let cost = 0;
  let revenue = 0;
  let toMaster = 0;
  if (MULTI.includes(type)) {
    (data.entries || []).forEach((e) => {
      cost += toEgp(e.cost, e.costCurrency);
      revenue += toEgp(e.revenue, e.revenueCurrency);
    });
  } else if (type === 'Cash to Master') {
    const amount = num(data.amount);
    const share = data.shareMode === 'fixed' ? num(data.fixedRevenue) : (amount * num(data.percentage)) / 100;
    const ours = Math.max(0, Math.min(share, amount));
    revenue = toEgp(ours, data.amountCurrency);
    toMaster = toEgp(amount - ours, data.amountCurrency);
  } else { // every other service, Crew Change and Others / Remarks included
    cost = toEgp(data.cost, data.costCurrency);
    revenue = toEgp(data.revenue, data.revenueCurrency);
  }
  return {
    cost_egp: cost,
    revenue_egp: revenue,
    profit_egp: revenue - cost,
    to_master_egp: toMaster,
    rate_missing: rateMissing,
  };
}
