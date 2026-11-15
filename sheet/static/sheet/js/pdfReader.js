// Reading a PDF's text in the browser with the bundled (patched) pdf.js. Nothing is uploaded.
import { PDF } from './config.js';

/** Concatenated text of every page; items are joined with spaces, which the parsers expect. */
export async function extractPdfText(file) {
  const pdfjs = await import(/* @vite-ignore */ PDF.lib);
  pdfjs.GlobalWorkerOptions.workerSrc = PDF.worker;
  const pdf = await pdfjs.getDocument({ data: await file.arrayBuffer(), isEvalSupported: false }).promise;
  let text = '';
  for (let i = 1; i <= pdf.numPages; i += 1) {
    const content = await (await pdf.getPage(i)).getTextContent();
    text += `${content.items.map((item) => item.str).join(' ')}\n`;
  }
  return text;
}
