// User feedback: the status dot in the header and error boxes inside the modal.
import { $ } from './util.js';

export function setStatus(kind, text) {
  $('#status').className = `status ${kind}`;
  $('#status-text').textContent = text;
}

export function showError(message) {
  const body = $('#modal .m-body');
  if (!body) {
    alert(message);
    return;
  }
  let box = $('#modal .error');
  if (!box) {
    box = document.createElement('div');
    box.className = 'error';
    body.prepend(box);
  }
  box.textContent = message; // textContent: never HTML
  box.scrollIntoView({ block: 'nearest' });
}
