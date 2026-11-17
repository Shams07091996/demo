// Reading a PDF's text in the browser with the bundled (patched) pdf.js. Nothing is uploaded.
import { PDF } from './config.js';

let policy = null; // created once: the browser refuses a second policy with the same name
let worker = null; // started once and reused while it works
let workerFailed = null; // a promise that rejects when the current worker fails to load or crashes

/**
 * The PDF.js worker, started by us (not by PDF.js) so the page's Trusted Types rule holds: the one policy,
 * "pdfjs-worker" (allowed by the CSP), turns exactly the bundled worker's URL into a script URL and refuses
 * anything else. A worker that fails is dropped, so the next read starts a fresh one.
 */
function pdfWorker() {
  if (worker) return worker;
  if (!policy && window.trustedTypes) {
    policy = window.trustedTypes.createPolicy('pdfjs-worker', {
      createScriptURL: (value) => {
        if (value !== PDF.worker) throw new TypeError('Only the bundled PDF.js worker may be loaded.');
        return value;
      },
    });
  }
  const started = new Worker(policy ? policy.createScriptURL(PDF.worker) : PDF.worker, { type: 'module' });
  workerFailed = new Promise((_, reject) => {
    started.addEventListener('error', () => {
      if (worker === started) worker = null;
      started.terminate();
      reject(new Error('The PDF reader (worker) could not start. Reload the page and try again.'));
    });
  });
  workerFailed.catch(() => {}); // nobody may be waiting when it fails
  worker = started;
  return worker;
}

/** Concatenated text of every page; items are joined with spaces, which the parsers expect. */
export async function extractPdfText(file) {
  const pdfjs = await import(/* @vite-ignore */ PDF.lib);
  pdfjs.GlobalWorkerOptions.workerPort = pdfWorker();
  const failed = workerFailed;
  // PDF.js would wait forever for a worker that never answers: fail as soon as the worker does.
  const pdf = await Promise.race([pdfjs.getDocument({ data: await file.arrayBuffer(), isEvalSupported: false }).promise, failed]);
  let text = '';
  for (let i = 1; i <= pdf.numPages; i += 1) {
    const content = await Promise.race([(await pdf.getPage(i)).getTextContent(), failed]);
    text += `${content.items.map((item) => item.str).join(' ')}\n`;
  }
  return text;
}
