// Talking to the server: one fetch wrapper, plus `mutate` for saves that show status / errors.
import { setStatus, showError } from './feedback.js';

const csrfToken = () => document.querySelector('meta[name="csrf-token"]').content;

export async function api(url, method = 'GET', payload) {
  const response = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  if (response.status === 401) {
    location.href = '/login/';
    throw new Error('Please log in again.');
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.error || 'Something went wrong.';
    throw new Error(data.ref ? `${message} (reference ${data.ref})` : message);
  }
  return data;
}

/** Run a save, showing "Saving… / Saved / Failed" and any error inside the open modal. */
export async function mutate(action) {
  setStatus('saving', 'Saving…');
  try {
    const result = await action();
    setStatus('ok', 'Saved ✓');
    return result;
  } catch (error) {
    setStatus('error', 'Failed');
    showError(error.message);
    throw error;
  }
}
