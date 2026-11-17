// Reading a PDF's text in the browser with the bundled (patched) pdf.js. Nothing is uploaded.
import { PDF } from './config.js';

let worker = null;

/**
 * The PDF.js worker, started by us (not by PDF.js) so the page's Trusted Types rule holds: the one policy,
 * "pdfjs-worker" (allowed by the CSP), turns exactly the bundled worker's URL into a script URL and refuses
 * anything else. Started once and reused.
 */
function pdfWorker() {
  if (worker) return worker;
  let url = PDF.worker;
  if (window.trustedTypes) {
    const policy = window.trustedTypes.createPolicy('pdfjs-worker', {
      createScriptURL: (value) => {
        if (value !== PDF.worker) throw new TypeError('Only the bundled PDF.js worker may be loaded.');
        return value;
      },
    });
    url = policy.createScriptURL(PDF.worker);
  }
  worker = new Worker(url, { type: 'module' });
  return worker;
}

/** Concatenated text of every page; items are joined with spaces, which the parsers expect. */
export async function extractPdfText(file) {
  const pdfjs = await import(/* @vite-ignore */ PDF.lib);
  pdfjs.GlobalWorkerOptions.workerPort = pdfWorker();
  const pdf = await pdfjs.getDocument({ data: await file.arrayBuffer(), isEvalSupported: false }).promise;
  let text = '';
  for (let i = 1; i <= pdf.numPages; i += 1) {
    const content = await (await pdf.getPage(i)).getTextContent();
    text += `${content.items.map((item) => item.str).join(' ')}\n`;
  }
  return text;
}
