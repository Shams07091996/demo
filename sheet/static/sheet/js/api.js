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
    const error = new Error(data.ref ? `${message} (reference ${data.ref})` : message);
    error.status = response.status;
    error.data = data; // e.g. a 409's `conflict`: who saved the record meanwhile (see conflict.js)
    throw error;
  }
  return data;
}

/**
 * A file download (LOG letter, master receipt): fetch it, then save the answer under the server's file name.
 * Returns null when saved, or the error message to show (the JSON `error`, or `failed`).
 */
export async function download(url, failed, payload) {
  const response = await fetch(url, payload === undefined ? { credentials: 'same-origin' } : {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify(payload),
  });
  if (response.status === 401) {
    location.href = '/login/';
    return failed;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    return body.error || failed;
  }
  const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '');
  const blobUrl = URL.createObjectURL(await response.blob());
  const save = document.createElement('a');
  save.href = blobUrl;
  save.download = name ? name[1] : 'download.pdf';
  save.click();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  return null;
}

/**
 * Run a save, showing "Saving… / Saved / Failed" and any error inside the open modal. A save refused because someone
 * saved the record meanwhile (409) goes to `onConflict` (the dialog's warning panel) instead of the error box.
 */
export async function mutate(action, onConflict) {
  setStatus('saving', 'Saving…');
  try {
    const result = await action();
    setStatus('ok', 'Saved');
    return result;
  } catch (error) {
    if (error.status === 409 && error.data?.conflict && onConflict) {
      setStatus('error', 'Not saved');
      onConflict(error.data.conflict);
    } else {
      setStatus('error', 'Failed');
      showError(error.message);
    }
    throw error;
  }
}
