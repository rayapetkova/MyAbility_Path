import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { fetchNearby } from './overpass.js';
import { getStats, addReview, addReport } from './db.js';

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const KIND = {
  public: { n: 'Обществена тоалетна', i: '🚻', c: '#1265A8' },
  eco: { n: 'Екотой', i: '🌿', c: '#2E9E6B' },
  venue: { n: 'Заведение с достъп', i: '☕', c: '#D98E04' },
};
const PROBLEMS = ['Няма хартия', 'Заключено', 'Мръсно', 'Не работи'];
const SOFIA = [42.6977, 23.3219];
const MOD = { left: 'наляво', right: 'надясно', 'slight left': 'леко наляво', 'slight right': 'леко надясно', 'sharp left': 'рязко наляво', 'sharp right': 'рязко надясно', uturn: 'обратно' };

const map = L.map('map', { zoomControl: false }).setView(SOFIA, 14);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map);
let me = null, meMarker = null, items = [], stats = {}, markers = [], sel = null, routeLayer = null;
const filters = new Set();

const toast = m => { const t = $('toast'); t.textContent = m; t.style.opacity = 1; clearTimeout(t._h); t._h = setTimeout(() => t.style.opacity = 0, 2600); };
const dist = (a, b) => { const r = x => x * Math.PI / 180, R = 6371e3, h = Math.sin(r(b[0] - a[0]) / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(r(b[1] - a[1]) / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); };
const fmtD = m => m < 1000 ? `${Math.round(m / 10) * 10} м` : `${(m / 1000).toFixed(1)} км`;
const bad = t => (stats[t.id]?.blocking_reports || 0) > 0;
const avg = t => stats[t.id]?.review_count ? Number(stats[t.id].avg_rating) : 0;
const match = t => (!filters.has('acc') || t.acc) && (!filters.has('baby') || t.baby) && (!filters.has('free') || t.fee === 'Безплатна') && (!filters.has('clean') || avg(t) >= 4.3);

// 1) Геолокация – при отваряне/презареждане и с бутона 📍
function locate() {
  toast('Търся местоположението ти…');
  if (!navigator.geolocation) return start(SOFIA, 'Браузърът не поддържа геолокация – показвам центъра на София');
  navigator.geolocation.getCurrentPosition(
    p => start([p.coords.latitude, p.coords.longitude]),
    () => start(SOFIA, 'Няма достъп до локацията – показвам центъра на София'),
    { enableHighAccuracy: true, timeout: 10000 });
}

// 2) Данни от OpenStreetMap + статистика от базата
async function start(pos, msg) {
  me = pos; closeSheet(); stopNav(); if (msg) toast(msg);
  meMarker?.remove();
  meMarker = L.marker(me, { icon: L.divIcon({ className: '', html: '<div class="me"></div>', iconSize: [18, 18] }), zIndexOffset: 1000 })
    .addTo(map).bindTooltip('Ти си тук', { permanent: true, direction: 'top', offset: [0, -12] });
  map.setView(me, 16);
  $('loading').classList.remove('hidden');
  try {
    const { els, r } = await fetchNearby(...me);
    items = els.map(e => ({ ...e, d: dist(me, [e.lat, e.lon]) })).sort((a, b) => a.d - b.d);
    stats = await getStats(items.map(e => e.id));
    if (!items.length) toast('Не намерих тоалетни в радиус 5 км');
    else {
      if (r > 800) toast(`Най-близката е на ${fmtD(items[0].d)}`);
      map.fitBounds(L.latLngBounds([me, ...items.slice(0, 5).map(i => [i.lat, i.lon])]).pad(0.25));
    }
  } catch (e) { console.error(e); toast('Грешка при зареждане. Натисни 📍 за нов опит.'); }
  $('loading').classList.add('hidden');
  render();
}

function render() {
  markers.forEach(m => m.remove()); markers = [];
  items.filter(match).forEach(t => {
    const k = KIND[t.kind];
    const icon = L.divIcon({ className: '', iconSize: [36, 36], iconAnchor: [18, 18],
      html: `<div class="pin ${sel === t.id ? 'sel' : ''}" style="border-color:${k.c}">${k.i}<i class="dot" style="background:${bad(t) ? '#F2543D' : '#2E9E6B'}"></i></div>` });
    markers.push(L.marker([t.lat, t.lon], { icon, title: t.name }).addTo(map).on('click', () => openSheet(t.id)));
  });
}

// 3) Панел с детайли
function openSheet(id) {
  sel = id;
  const t = items.find(x => x.id === id), k = KIND[t.kind], s = stats[id], ok = !bad(t);
  const rp = s?.blocking_reports ? `<div class="text-sm mb-3 font-bold" style="color:var(--red)">Докладван проблем (последните 24 ч)</div>` : '';
  $('sheet').innerHTML = `<div class="mx-auto mb-3 rounded-full" style="width:42px;height:4px;background:var(--line)"></div>
   <div class="flex justify-between gap-3 items-start"><div>
     <div class="text-xs font-bold" style="color:${k.c}">${k.i} ${k.n} · ${fmtD(t.d)}</div>
     <div class="font-extrabold text-xl leading-tight">${esc(t.name)}</div>
     <div class="text-sm" style="color:var(--mute)">${esc(t.addr || 'Адресът не е въведен в OSM')}</div></div>
     <div class="tag" style="background:${ok ? '#2E9E6B' : '#F2543D'};color:#fff;flex:none">${ok ? 'Работи' : 'Проблем'}</div></div>
   <div class="grid grid-cols-2 gap-2 my-3 text-sm">
     <div class="rounded-xl p-2" style="background:var(--bg)"><div class="text-xs font-bold" style="color:var(--mute)">Работно време</div><div class="font-bold">${esc(t.hours)}</div></div>
     <div class="rounded-xl p-2" style="background:var(--bg)"><div class="text-xs font-bold" style="color:var(--mute)">Цена</div><div class="font-bold">${esc(t.fee)}</div></div></div>
   <div class="flex items-center gap-2 mb-2"><span style="color:#F5B301;font-size:18px">★</span>
     <b>${s?.review_count ? avg(t).toFixed(1) + '/5' : '–'}</b><span class="text-sm" style="color:var(--mute)">${s?.review_count ? `чистота · ${s.review_count} отзива` : 'още няма отзиви'}</span></div>
   <div class="flex gap-1 flex-wrap mb-3">${t.acc ? '<span class="tag">♿ Достъпна</span>' : ''}${t.baby ? '<span class="tag">🍼 Преповиване</span>' : ''}${t.fee === 'Безплатна' ? '<span class="tag">💶 Безплатна</span>' : ''}${avg(t) >= 4.3 ? '<span class="tag">🧼 Поддържана</span>' : ''}</div>
   ${rp}
   <div class="flex gap-2 mb-3"><button id="go" class="btn text-white flex-1" style="background:var(--blue)">Навигирай до тук</button>
     <button id="rep" class="btn" style="border:2px solid var(--red);color:var(--red)">Докладвай проблем</button></div>
   <div id="repBox" class="hidden flex gap-2 flex-wrap mb-3">${PROBLEMS.map(p => `<button class="chip" data-p="${p}">${p}</button>`).join('')}</div>
   <div class="text-sm font-bold mb-1">Оцени чистотата</div>
   <div id="rate">${[1, 2, 3, 4, 5].map(i => `<button class="star" data-s="${i}" aria-label="${i} звезди">★</button>`).join('')}</div>`;
  $('sheet').classList.add('open'); render();
  $('go').onclick = () => navigate(t);
  $('rep').onclick = () => $('repBox').classList.toggle('hidden');
  $('repBox').onclick = async e => { const p = e.target.dataset.p; if (!p) return; await submit(addReport(id, p), id, 'Докладвано: ' + p); };
  $('rate').onclick = async e => { const v = +e.target.dataset.s; if (!v) return; await submit(addReview(id, v), id, 'Благодарим за оценката!'); };
}
async function submit(promise, id, okMsg) {
  const { error } = await promise;
  if (error) { console.error(error); return toast('Не успях да запиша. Опитай пак.'); }
  stats = { ...stats, ...(await getStats([id])) }; toast(okMsg); openSheet(id);
}
function closeSheet() { sel = null; $('sheet').classList.remove('open'); render(); }

// 4) Реален маршрут пеша (OSRM на openstreetmap.de)
async function navigate(t) {
  try {
    const u = `https://routing.openstreetmap.de/routed-foot/route/v1/foot/${me[1]},${me[0]};${t.lon},${t.lat}?overview=full&geometries=geojson&steps=true`;
    const route = (await (await fetch(u)).json()).routes[0];
    routeLayer?.remove();
    routeLayer = L.geoJSON(route.geometry, { style: { color: '#1265A8', weight: 6, dashArray: '1 10', lineCap: 'round' } }).addTo(map);
    map.fitBounds(routeLayer.getBounds().pad(0.3));
    const steps = route.legs[0].steps;
    const txt = s => s.maneuver.type === 'arrive' ? 'Пристигна си' : s.maneuver.type === 'depart' ? `Тръгни${s.name ? ' по ' + s.name : ' напред'}` :
      (MOD[s.maneuver.modifier] ? `Завий ${MOD[s.maneuver.modifier]}` : 'Продължи направо') + (s.name ? ' по ' + s.name : '');
    $('navTitle').textContent = `${fmtD(route.distance)} · ${Math.max(1, Math.round(route.duration / 60))} мин пеша`;
    $('navStep').textContent = `${txt(steps[0])} ${fmtD(steps[0].distance)}`;
    $('navNext').textContent = steps[1] ? 'След това: ' + txt(steps[1]) : '';
    $('nav').classList.remove('hidden'); closeSheet();
  } catch (e) { console.error(e); toast('Не успях да изчертая маршрута'); }
}
function stopNav() { routeLayer?.remove(); routeLayer = null; $('nav').classList.add('hidden'); }

$('stop').onclick = stopNav;
$('locate').onclick = locate;
map.on('click', closeSheet);
$('chips').onclick = e => {
  const f = e.target.dataset.f; if (!f) return;
  filters.has(f) ? filters.delete(f) : filters.add(f); e.target.classList.toggle('on');
  if (sel && !match(items.find(x => x.id === sel))) closeSheet(); else render();
  if (items.length && !items.some(match)) toast('Няма тоалетни с тези филтри');
};
$('nearest').onclick = () => {
  const t = items.find(x => match(x) && !bad(x));
  if (t) { map.panTo([t.lat, t.lon]); openSheet(t.id); } else toast('Няма подходяща тоалетна наблизо');
};
locate();
