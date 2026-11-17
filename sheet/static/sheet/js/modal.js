// The single modal dialog everything opens in.
import { el } from './config.js';
import { setChildren } from './dom.js';
import { resetContext } from './state.js';

/** Open the dialog with the given nodes (built with h()). */
export function openModal(...content) {
  setChildren(el.modal, ...content);
  el.overlay.classList.add('open');
  el.modal.scrollTop = 0;
}

export function closeModal() {
  el.overlay.classList.remove('open');
  setChildren(el.modal);
  resetContext();
}

export const isModalOpen = () => el.overlay.classList.contains('open');
