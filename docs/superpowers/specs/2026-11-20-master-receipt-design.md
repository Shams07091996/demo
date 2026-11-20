# Master receipt — design (short)

Approved by the user 2026-11-20.

## Why

The user hands the vessel's master a printed paper to sign and stamp, saying which services ARKAS rendered. Today it
is a Word file ("name of port.docx") filled by hand. They want it as a PDF from the app, with the wording editable
just before downloading. What happens to the paper afterwards is not the app's concern (not stored, not tracked).

## What

- A **Receipt** button on each service in the vessel form (`js/modals/service.js` area, next to where LOG is), for
  edit roles only (admin and port users; not read-only).
- It opens a small form, pre-filled and fully editable:
  - **Port** (the vessel's port label), **Date** (today, Cairo, DD/MM/YYYY), **Vessel** (name).
  - **Services**: a multi-line text box. Pre-filled with one line: the service type plus that service's **revenue
    written as "cost"** (to the vessel it is a cost), e.g. `Landing with cost $120`, `Fresh Water with cost EGP 2,500`.
    Multi-entry services (Delivery Parcels / Courier, Landing) add up their entries' revenue per currency; Cash to
    Master uses its revenue (percentage or fixed share). No revenue -> just the service type. The user types over it
    freely ("Arrange 5 shore pass with cost $50"); several lines allowed.
- **Download** makes the PDF on the server from the submitted text.
- Nothing typed is saved; the form starts from the service every time. The download is recorded in the History
  (action `receipt`), like the LOG letter (`letter`).

## The PDF

Built with the LOG letter's own PDF code (`logpdf.py`: standard library only, WinAnsi, JPEGs raw). Logo and footer
from `DJANGO_LETTERHEAD_DIR`; **no stamp**. Layout follows the Word file:

```
{Port}: {date}
MV/ {vessel}

WHOM IT MAY CONCERN

I, the undersigned master of m/v {vessel} declare the following services have been
rendered from Messrs ARKAS EGYPT SAE
{the service lines}

Master                                   (space to sign)

Ship's stamp                             (space to stamp)
```

No separate revenue line: any amount is only in the user's text.

## Rules

- Scoped like everything else (`access.scoped_vessels`), `require_edit`, rate limited like the CSV export / LOG.
- Input through `validators.py`: whitelisted keys, length limits (refused, never cut), plain text only; every value
  written as an escaped PDF string, never `{{ }}`.
- English letters only (WinAnsi, like the LOG: Ş -> S, Arabic / Cyrillic -> ?).

## Approaches

1. **Server PDF with the LOG's code (picked):** same look as the LOG, a direct download, no new dependency.
2. Browser Print -> Save as PDF: Arabic would work, but a print dialog every time and browser-dependent margins and
   headers. Set aside.

## Non-goals

No receipt numbering, no storage, no list of past receipts, no stamp, no Arabic.

## Left to the builder

- How the browser downloads a PDF from a POST (fetch + blob link, or a plain form post) within the strict CSP and
  `dom.js` rules.
- Exact spacing, fonts (Helvetica like the LOG), file name (e.g. `Receipt-<vessel>-<date>.pdf`, cleaned like the LOG's).
- Text limits (suggested: port / vessel 80, date 20, services 2000 characters, 40 lines).
