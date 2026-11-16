`# Local patches to PDF.js 4.10.38
`
`Re-apply these after any PDF.js update (`sheet/tests_frontend_safety.py` fails until you do).
`
`1. `pdf.min.mjs` and `pdf.worker.min.mjs`: the eval probe
`   \`try{new Function("");return!0}catch{return!1}\` → \`return!1\` (PDF.js then never tries to compile code).
`2. `pdf.worker.min.mjs`: the PostScript-function compiler (the CVE-2024-4367 path)
`   \`if(e)return new Function("src","srcOffset","dest","destOffset",e)\` → removed (PDF.js falls back to its
`   built-in interpreter).
