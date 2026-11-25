# Parcels extras (piece 2 of the HTML gaps)

**Why:** the manager's HTML records how a parcel moves and whether the courier was paid; the app had only AWB,
weight and money per line.

**Approved (2026-11-25):** fields on the service, through `constants.SERVICE_FIELDS` (piece 1's table), not per AWB
line (more exact but a bigger form). No migration, nothing required, no separate Parcels page.

- Delivery Parcels, Landing: Transfer type (Vessel-to-Vessel / Vessel-to-Courier); Receiving vessel (free text, not
  a link to a vessel: that would need port checks), only for Vessel-to-Vessel; Courier (DHL / FedEx / Aramex /
  Other), only for Vessel-to-Courier; Courier payment (Paid / Not Paid).
- Delivery Courier: Courier, Delivery status (Pending / Dispatched / Delivered), Courier payment.
- A field's `when` [key, value]: the form hides it (and empties it) under another choice; the server refuses a
  value under another choice ("Receiving vessel is only for Vessel-to-Vessel.").
- Card and Summary show the filled fields above the lines.
