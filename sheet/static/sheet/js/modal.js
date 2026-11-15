// The single modal dialog everything opens in.
import { el } from './config.js';
import { resetContext } from './state.js';

export function openModal(html) {
  el.modal.innerHTML = html;
  el.overlay.classList.add('open');
  el.modal.scrollTop = 0;
}

export function closeModal() {
  el.overlay.classList.remove('open');
  el.modal.innerHTML = '';
  resetContext();
}

export const isModalOpen = () => el.overlay.classList.contains('open');
