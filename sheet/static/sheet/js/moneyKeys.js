// Which keys of a service's data are money (the twin of sheet/moneyaccess.py SERVICE_MONEY): without money.edit the
// server never sends them and refuses them, so the service dialog leaves them out of what it saves. Pure.

const MULTI_TYPES = ['Delivery Parcels', 'Delivery Courier', 'Landing']; // constants.MULTI_TYPES
const PRICE_KEYS = ['cost', 'costCurrency', 'revenue', 'revenueCurrency'];
const SINGLE_MONEY = [...PRICE_KEYS, 'exchangeRate'];
const CASH_MONEY = ['amount', 'amountCurrency', 'shareMode', 'percentage', 'fixedRevenue', 'exchangeRate'];

const topKeys = (type) => {
  if (MULTI_TYPES.includes(type)) return ['exchangeRate'];
  return type === 'Cash to Master' ? CASH_MONEY : SINGLE_MONEY;
};
const without = (item, keys) => Object.fromEntries(Object.entries(item).filter(([key]) => !keys.includes(key)));

/** A copy of a service's data without its money keys (uids, quantities, names and notes stay). */
export function stripMoney(type, data) {
  const out = without(data || {}, topKeys(type));
  if (Array.isArray(out.entries)) out.entries = out.entries.map((entry) => without(entry, PRICE_KEYS));
  if (Array.isArray(out.onSigners)) out.onSigners = out.onSigners.map((member) => without(member, ['brokenVisa']));
  return out;
}
