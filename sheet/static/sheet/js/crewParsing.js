// Reading crew details out of pasted text and flight-itinerary text. Pure functions: no DOM, easy to test.

/** "Surname: X / Given name: Y / Rank: Z / Nationality: W" lines -> structured fields. */
export function parsePersonal(text) {
  const parsed = {};
  for (const line of (text || '').split('\n').map((l) => l.trim()).filter(Boolean)) {
    const lower = line.toLowerCase();
    const value = line.includes(':') ? line.split(':').slice(1).join(':').trim() : '';
    if (!parsed.lastName && (lower.startsWith('last name') || lower.startsWith('surname'))) parsed.lastName = value;
    else if (!parsed.firstName && (lower.startsWith('given name') || lower.startsWith('name:'))) parsed.firstName = value;
    else if (!parsed.rank && (lower.startsWith('rank') || lower.startsWith('position'))) parsed.rank = value;
    else if (!parsed.nationality && lower.startsWith('nationalit')) parsed.nationality = value;
  }
  if (parsed.firstName && parsed.lastName) parsed.name = `${parsed.firstName} ${parsed.lastName}`;
  else if (parsed.firstName || parsed.lastName) parsed.name = parsed.firstName || parsed.lastName;
  return parsed;
}

/** Hand-typed blocks: "FLIGHT TK123 - Airline  DEPARTURE: City  13 NOV 10:00  ARRIVAL: ...". */
function parseFlightManual(text) {
  const segments = [];
  for (const block of (text || '').split(/FLIGHT\s+/i).filter((b) => b.trim())) {
    const flight = block.match(/^([A-Z]{2}\s*\d+)\s*-\s*([^\n]+)/);
    if (!flight) continue;
    const departure = block.match(/DEPARTURE:\s*([^\n,]+(?:,[^\n]+)?)\s{2,}(\d{1,2}\s+[A-Z]{3}\s+\d{2}:\d{2})/i);
    const arrival = block.match(/ARRIVAL:\s*([^\n,]+(?:,[^\n]+)?)\s{2,}(\d{1,2}\s+[A-Z]{3}\s+\d{2}:\d{2})/i);
    segments.push({
      flightNo: flight[1].replace(/\s+/, ''),
      airline: flight[2].trim(),
      departureCity: departure ? departure[1].trim() : '',
      departureTime: departure ? departure[2].trim() : '',
      arrivalCity: arrival ? arrival[1].trim() : '',
      arrivalTime: arrival ? arrival[2].trim() : '',
    });
  }
  return segments;
}

/** Pasted travel-agent itineraries ("Flight Information … Origin … Destination … Departing"): the Egypt departure leg only. */
function parseItineraryFormat(text) {
  const dateMatch = text.match(/Travel Details\s+\w+\s+(\d{1,2}\s+\w+\s+\d{4})/i);
  const travelDate = dateMatch ? dateMatch[1].trim() : '';
  for (const block of text.split(/Flight Information/i).slice(1)) {
    const originMatch = block.match(/Origin\s+([\s\S]+?)\s+Destination/i);
    const origin = originMatch ? originMatch[1].trim() : '';
    if (!/alexandria|cairo|alex|cai|borg/i.test(origin)) continue;
    const destination = block.match(/Destination\s+([\s\S]+?)\s+Departing/i);
    const departing = block.match(/Departing\s+([\d:]+)/i);
    const airline = block.match(/(?:^|\s)Airline\s+(?!Booking)([\s\S]+?)\s+Flight\s+/i);
    const flightNo = block.match(/\bFlight\s+([A-Z]{2}\d+)/i);
    const time = departing ? departing[1].trim() : '';
    return [{
      flightNo: flightNo ? flightNo[1].trim() : '',
      airline: airline ? airline[1].trim() : '',
      departureCity: origin,
      arrivalCity: destination ? destination[1].trim() : '',
      departureTime: travelDate ? `${travelDate} ${time}` : time,
      arrivalTime: '',
      date: travelDate,
    }];
  }
  return [];
}

export function parseFlightText(text) {
  const manual = parseFlightManual(text);
  return manual.length ? manual : parseItineraryFormat(text || '');
}
