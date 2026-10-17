// Взима тоалетни и заведения с тоалетна от OpenStreetMap през Overpass API
const URL = 'https://overpass-api.de/api/interpreter';
const NAMES = { public: 'Обществена тоалетна', eco: 'Екотой', venue: 'Заведение' };

function kindOf(t) {
  if (t.amenity !== 'toilets') return 'venue';
  const eco = /chemical|pit|bucket/.test(t['toilets:disposal'] || '') || /екотой|eco/i.test(t.name || '');
  return eco ? 'eco' : 'public';
}

export async function fetchNearby(lat, lon) {
  // Разширяваме радиуса, ако наблизо има малко резултати
  for (const r of [800, 2000, 5000]) {
    const around = `(around:${r},${lat},${lon})`;
    // Ако искаш ПОВЕЧЕ заведения: махни ["toilets"="yes"] (но достъпът не е гарантиран)
    const q = `[out:json][timeout:25];(
      nwr["amenity"="toilets"]${around};
      nwr["amenity"~"^(restaurant|cafe|fast_food|fuel|pub)$"]["toilets"="yes"]${around};
    );out center tags 80;`;
    const res = await fetch(URL, { method: 'POST', body: 'data=' + encodeURIComponent(q) });
    if (!res.ok) throw new Error('Overpass ' + res.status);
    const els = (await res.json()).elements
      .map(e => {
        const t = e.tags || {}, kind = kindOf(t);
        return {
          id: `${e.type}/${e.id}`, kind,
          lat: e.lat ?? e.center?.lat, lon: e.lon ?? e.center?.lon,
          name: t.name || NAMES[kind],
          hours: t.opening_hours || 'Няма данни',
          fee: kind === 'venue' ? 'За клиенти' : t.fee === 'yes' ? (t.charge || 'Платена') : t.fee === 'no' ? 'Безплатна' : 'Няма данни',
          acc: ['yes', 'limited'].includes(t.wheelchair),
          baby: t.changing_table === 'yes',
          addr: [t['addr:street'], t['addr:housenumber']].filter(Boolean).join(' '),
        };
      })
      .filter(e => e.lat && e.lon);
    if (els.length >= 3 || r === 5000) return { els, r };
  }
}
