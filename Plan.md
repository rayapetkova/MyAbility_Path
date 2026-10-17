# Able Route Notes — PoC plan

Oct 17, 2026 · @Stefan

A web app that records a walk on any phone (Android or iPhone), shows it on a map, and lets people pin notes on the street. Stage 0 (the one-day demo) is planned in full detail; later stages are outlined with their test gates.

## Goal and definition of done

By the end of day 1, two people on two different phones (one Android, one iPhone) can each record a 20-minute walk in Sofia, pin at least 3 notes with a photo, and see both walks and all notes on one shared map on a laptop.

**In scope for the demo**

- Record a trip with Start / Stop while the screen stays on
- Live line on the map as you walk, plus a live dot for others
- Notes: long-press the map (or tap "Note here"), pick a category, add text and an optional photo, drag the pin to the exact spot
- Trip history: list of trips, tap one to redraw it
- Export all notes and tracks as GeoJSON and GPX
- Works offline for short gaps (underpass, weak signal) and uploads afterwards

**Out of scope for the demo**

- Tracking with the screen locked (stage 1)
- Snapping tracks to streets with OSRM (stage 2)
- Rating whole street segments (stage 2)
- App store apps (stage 3)
- Real accounts with passwords: the demo uses anonymous sign-in plus a display name

**Done means all of these pass**

- [ ] App opens from a link on both phones over HTTPS and asks for location
- [ ] A 20-minute walk produces one continuous line with no gaps longer than 30 s outside tunnels
- [ ] Turning on airplane mode for 2 minutes mid-walk loses no points
- [ ] Notes appear on the second phone within 5 s of saving
- [ ] Exported GPX opens in a GPS app (e.g. OsmAnd) and the GeoJSON opens on geojson.io

## Roadmap

Each stage ends with a gate: the stage is done only when its test passes. Stages build on the same database, so nothing is thrown away.

| Stage | When | What gets built | Gate (the test that must pass) |
| --- | --- | --- | --- |
| 0. Demo web app | Day 1 | Everything in this doc: GPS recording, offline queue, map, notes, history, export | Definition of done above |
| 1. Screen-off tracking | Days 2–3 | Telegram bot or OwnTracks feeding the same `points` table through a Supabase Edge Function | A 30-min walk with the phone locked in a pocket gives a continuous line on both Android and iPhone |
| 2. Pilot | Weeks 2–4 | Note categories agreed with users, still-there / gone votes, Level 1 smoothing + Level 2 OSRM snapping, street-segment colours | 5–10 people from the community each record 3+ walks; at least half say they would use it again |
| 3. Native app | Month 2 | Same web code wrapped with Capacitor + background-location plugin; TestFlight + Android test build | 1-hour walk in background, battery use under \~10% per hour, no lost points |
| 4. Public release | Month 3+ | Privacy policy, GDPR assessment, store listings, export to OpenStreetMap / Call Sofia | Both stores approve the app; data deletion works on request |

The battery figure in stage 3 is a target to measure, not a known value.

## Demo architecture

One static web app talks directly to Supabase; there is no server code of our own in stage 0.

**Data flow for a recorded walk**

1. The browser's Geolocation API gives a position about once per second while moving.
2. The filter (step 3) drops bad readings and keeps one point per \~5 m.
3. Each kept point gets a client-made UUID and goes into the offline queue in IndexedDB.
4. Every 10 s (and on Stop, and when the phone comes back online) the uploader sends all queued points in one HTTPS request to Supabase.
5. Supabase saves them in Postgres; Realtime pushes new rows over a WebSocket to anyone watching.
6. The map draws the line from local points while recording, and from the database when viewing history.

**Data flow for a note**

1. Long-press on the map or tap "Note here" → a draggable pin + a form.
2. The photo is shrunk to 1600 px in the browser and uploaded to Supabase Storage.
3. The note row (position, category, text, photo path) is inserted; Realtime shows it to others.

**Tools**

| Job | Tool |
| --- | --- |
| Build and dev server | Vite + TypeScript (no framework; plain DOM is enough for 3 screens) |
| Map | Leaflet 1.9 with OpenStreetMap tiles, `preferCanvas: true` |
| GPS | Browser Geolocation API (`watchPosition`) |
| Keep screen on | Screen Wake Lock API |
| Geometry maths | Turf.js (distance, simplify) |
| Offline queue | `idb-keyval` (IndexedDB) |
| Backend | Supabase: Postgres + PostGIS, Auth (anonymous), Storage, Realtime |
| Export | GeoJSON written by hand (plain JSON); `geojson-to-gpx` for GPX |
| Install to home screen | `vite-plugin-pwa` |
| Hosting | Netlify (deploy from GitHub; HTTPS included) |
| Location testing at the desk | Chrome DevTools → Sensors panel |

Package names are as I know them; check the exact names and versions when installing.

## Step 1: setup and hosting (\~45 min)

Get an empty app live on a real HTTPS link first, because GPS does not work on plain HTTP and testing on real phones matters more than anything else.

1. Create a Supabase project (EU region, e.g. Frankfurt). Note the project URL and the `anon` public key.
2. In Supabase → Authentication → enable **Anonymous sign-ins**.
3. Create a GitHub repo and scaffold: `npm create vite@latest able-notes -- --template vanilla-ts`.
4. Install: `npm i leaflet @supabase/supabase-js idb-keyval @turf/turf` and `npm i -D vite-plugin-pwa @types/leaflet`.
5. Put the keys in `.env` as `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (the anon key is public by design; security comes from the rules in step 2).
6. Connect the repo to Netlify, add the same two variables there, deploy.
7. Add a bare Leaflet map centred on Sofia (42.6977, 23.3219, zoom 15) with the OSM attribution.

**File layout**

```
src/
  main.ts        app start, screens, buttons
  map.ts         Leaflet setup, layers, drawing
  gps.ts         watchPosition, filter, wake lock
  queue.ts       IndexedDB queue + uploader
  notes.ts       note form, photo resize, save
  db.ts          Supabase client, sign-in, queries
  export.ts      GeoJSON / GPX export
```

**Test before moving on**

- [ ] The Netlify link opens on an Android phone and an iPhone and shows the map of Sofia
- [ ] Pushing a commit redeploys within \~1 minute

## Step 2: database, rules and storage (\~45 min)

Three tables, PostGIS for positions, and row-level security so each person writes only their own rows while everyone can read everything (fine for a demo among the team).

```sql
create extension if not exists postgis;

create table profiles (
  id uuid primary key references auth.users on delete cascade,
  display_name text not null
);

create table trips (
  id uuid primary key,                 -- made on the phone
  user_id uuid not null default auth.uid() references auth.users,
  started_at timestamptz not null,
  ended_at timestamptz,
  device text                           -- e.g. 'iPhone 13 / Safari'
);

create table points (
  id uuid primary key,                 -- made on the phone, makes retries safe
  trip_id uuid not null references trips on delete cascade,
  user_id uuid not null default auth.uid(),
  recorded_at timestamptz not null,    -- GPS time, not upload time
  geom geography(Point, 4326) not null,
  accuracy_m real,
  speed_mps real,
  heading_deg real
);
create index on points (trip_id, recorded_at);

create table notes (
  id uuid primary key,
  user_id uuid not null default auth.uid(),
  trip_id uuid references trips,
  created_at timestamptz not null default now(),
  geom geography(Point, 4326) not null,
  category text not null,              -- see list below
  severity smallint check (severity between 1 and 3),
  body text,
  photo_path text                       -- path in the 'note-photos' bucket
);
create index on notes using gist (geom);

alter table profiles enable row level security;
alter table trips   enable row level security;
alter table points  enable row level security;
alter table notes   enable row level security;

-- everyone signed in can read; only the owner can write
create policy read_all on trips  for select to authenticated using (true);
create policy own_ins  on trips  for insert to authenticated with check (user_id = auth.uid());
create policy own_upd  on trips  for update to authenticated using (user_id = auth.uid());
-- same three policies for points, notes and profiles (profiles: id = auth.uid())

alter publication supabase_realtime add table points, notes;
```

The app sends positions as WKT text, e.g. `geom: 'SRID=4326;POINT(23.3219 42.6977)'` — longitude first. Reading back, a view returns plain numbers so the browser never parses PostGIS binary:

```sql
create view points_xy with (security_invoker = true) as  -- keeps the RLS rules
select id, trip_id, user_id, recorded_at, accuracy_m,
       st_y(geom::geometry) as lat, st_x(geom::geometry) as lon
from points;
-- same for notes_xy
```

**Storage:** a bucket `note-photos`, files at `<user_id>/<note_id>.jpg`; policy: signed-in users may upload into their own folder, everyone signed in may read.

**Note categories for the demo** (to be replaced with what the community says in the pilot): high curb · no ramp · broken pavement · cars on sidewalk · stairs only · steep slope · narrow passage · good / accessible · other.

**Test before moving on**

- [ ] In the Supabase SQL editor, insert a point as a test user and read it back through `points_xy`
- [ ] With the anon key from the browser console, writing a row with someone else's `user_id` is refused
- [ ] Two browser tabs subscribed to Realtime both receive a newly inserted note

## Step 3: GPS capture and filtering (\~1.5 h)

The browser delivers raw fixes about once per second; the filter decides which ones become points. This is the core logic of the demo.

**Starting a trip** (must run from a button tap — iPhone requires a user gesture for permissions and wake lock)

1. `tripId = crypto.randomUUID()`, `startedAt = now`; insert the trip row (queued like points, so it works offline).
2. Request the wake lock: `navigator.wakeLock.request('screen')`. Re-request on `visibilitychange` when the page becomes visible again, because the lock is released whenever the tab is hidden.
3. Start `navigator.geolocation.watchPosition(onFix, onError, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 })`.
4. Show a status bar: GPS accuracy, points recorded, points waiting to upload, time since last fix.

**Filter rules for each fix** (thresholds are starting values to tune in the field test)

| Rule | Keep the fix only if… | Why |
| --- | --- | --- |
| Warm-up | at least 5 s since Start, or accuracy ≤ 15 m | first fixes are often 50 m+ off |
| Accuracy | `coords.accuracy` ≤ 25 m | Wi-Fi/cell guesses and urban-canyon fixes |
| Freshness | fix timestamp is newer than the last kept one | browsers sometimes repeat cached fixes |
| Speed sanity | implied speed from last kept point ≤ 4 m/s (walking or wheelchair) | removes jumps |
| Spacing | distance from last kept point ≥ 5 m, **or** 30 s passed | thins the track; the 30 s rule keeps a heartbeat when standing still |

```ts
// gps.ts — core of the filter
const MAX_ACC = 25, MIN_DIST = 5, HEARTBEAT_MS = 30_000, MAX_SPEED = 4, WARMUP_MS = 5_000;
let last: Kept | null = null;

function onFix(p: GeolocationPosition) {
  const { latitude: lat, longitude: lon, accuracy, speed, heading } = p.coords;
  const t = p.timestamp;
  ui.showFix(accuracy, t);                         // always show raw status

  if (t - startedAt < WARMUP_MS && accuracy > 15) return;
  if (accuracy > MAX_ACC) return;
  if (last && t <= last.t) return;

  if (last) {
    const d = turf.distance([last.lon, last.lat], [lon, lat], { units: 'meters' });
    const dt = (t - last.t) / 1000;
    if (d / dt > MAX_SPEED && d > accuracy) return;  // jump
    if (d < MIN_DIST && t - last.t < HEARTBEAT_MS) return;
  }

  last = { lat, lon, t };
  const point = { id: crypto.randomUUID(), trip_id: tripId, recorded_at: new Date(t).toISOString(),
                  geom: `SRID=4326;POINT(${lon} ${lat})`, accuracy_m: accuracy,
                  speed_mps: speed, heading_deg: heading };
  queue.add('points', point);                      // step 4
  map.extendLiveLine(lat, lon);                    // step 5
}
```

**Errors to handle in `onError`**

- `PERMISSION_DENIED` → show how to allow location (iPhone: Settings → Safari → Location; Android: the lock icon in Chrome's address bar).
- `POSITION_UNAVAILABLE` / `TIMEOUT` → keep watching, show "No GPS signal"; mark a gap if it lasts over 30 s.

**Stopping a trip:** clear the watch, release the wake lock, set `ended_at`, flush the queue (step 4).

**Not in the demo:** Kalman smoothing and OSRM snapping. Store raw kept points; smoothing can be run on them later without re-walking.

**Test before moving on**

- [ ] At the desk: Chrome DevTools → Sensors → set a custom location, change it 10 m at a time; a point is kept only when expected
- [ ] Replay test: a small script feeds a recorded list of fixes (including a 300 m jump and an accuracy-80 m fix) into `onFix`; the jump and the bad fix are dropped
- [ ] On a real phone, walking around the block: the screen stays on for 10 minutes and the status bar shows accuracy updating

## Step 4: offline queue and batched upload (\~1 h)

Every write goes to IndexedDB first and is uploaded later, so a dead zone or a crash never loses data and the UI never waits for the network.

**Rules**

- Queue order matters: `trips` before `points` and `notes`, because points reference their trip.
- Every row carries its own UUID, and uploads use `upsert(..., { onConflict: 'id', ignoreDuplicates: true })`. A retried batch that partly arrived before inserts nothing twice.
- A trip's `ended_at` is a second upsert of the same trip row (not ignored), so it updates.
- Flush triggers: every 10 s while recording, on Stop, on the `online` event, on `visibilitychange` to hidden (best effort), and on app start (leftovers from last time).
- Only one flush runs at a time; up to 500 rows per request.
- On failure, rows stay queued; retry with backoff 10 s → 30 s → 60 s; show the waiting count in the status bar.

```ts
// queue.ts
import { get, set } from 'idb-keyval';
const TABLES = ['trips', 'points', 'notes'] as const;   // upload order; queued photos are sent with supabase.storage.upload() before 'notes'
let flushing = false;

export async function add(table: typeof TABLES[number], row: Row) {
  const q = (await get(table)) ?? [];
  q.push(row);
  await set(table, q);
}

export async function flush() {
  if (flushing || !navigator.onLine) return;
  flushing = true;
  try {
    for (const table of TABLES) {
      const q: Row[] = (await get(table)) ?? [];
      while (q.length) {
        const batch = q.slice(0, 500);
        const { error } = await supabase.from(table)
          .upsert(batch, { onConflict: 'id', ignoreDuplicates: table !== 'trips' });
        if (error) throw error;
        q.splice(0, batch.length);
        await set(table, q);                 // remove only what was confirmed
      }
    }
    ui.setWaiting(0);
  } catch (e) { scheduleRetry(); }
  finally { flushing = false; }
}
```

For the demo, keeping each table's queue as one array is fine (a 1-hour walk is \~700 points, \~100 KB). If queues grow large later, switch to one IndexedDB key per row.

**Photos** go through the same idea: the resized JPEG blob is queued under `photos` with its target path and uploaded before the note row that points at it.

**Test before moving on**

- [ ] Record for 1 minute, turn on airplane mode for 2 minutes, turn it off: the waiting count rises, then drops to 0, and the database has every point with no duplicates (`select count(*), count(distinct id) from points where trip_id = …`)
- [ ] Close the tab mid-walk, reopen: leftover points upload on start
- [ ] Make the network fail on purpose (DevTools → Network → Offline) during a flush: no rows lost, no duplicates after retry

## Step 5: map, live track and history (\~1.5 h)

The map has five layers on top of the OSM tiles; Leaflet keeps them aligned with the tiles automatically because all use latitude/longitude.

| Layer | What it shows | Source |
| --- | --- | --- |
| My live line | the trip being recorded | kept points in memory, extended on every new point |
| Me | blue dot + a circle sized to the GPS accuracy | every raw fix (even rejected ones), so the user sees what GPS is doing |
| Others live | one dot per other active walker | Realtime inserts on `points`, last point per user |
| History | selected past trips as lines | `points_xy` for that trip, ordered by `recorded_at` |
| Notes | pins coloured by category, popup with text + photo | `notes_xy` on load + Realtime inserts |

**Key logic**

- Create the map with `preferCanvas: true` so hundreds of points stay fast.
- Live line: `L.polyline([], {weight: 5})`, then `addLatLng()` per kept point. Follow mode keeps the map centred on the user until they pan by hand; a "re-centre" button turns it back on.
- History line: split a trip into pieces wherever two points are more than 30 s or 100 m apart, so tunnels and gaps are not drawn as straight lines through buildings.
- Trip list screen: `trips` ordered by `started_at` desc, showing user name, date, duration, distance (Turf `length` over the points).
- Realtime: one channel subscribed to inserts on `points` and `notes`; ignore your own rows (already drawn).
- Tiles: `https://tile.openstreetmap.org/{z}/{x}/{y}.png` with attribution © OpenStreetMap contributors, `maxZoom: 19`.

```ts
// history: draw one trip, broken at gaps
const { data } = await supabase.from('points_xy')
  .select('lat, lon, recorded_at').eq('trip_id', tripId).order('recorded_at');
const pieces: L.LatLngExpression[][] = [[]];
for (let i = 0; i < data.length; i++) {
  const p = data[i], prev = data[i - 1];
  if (prev && (Date.parse(p.recorded_at) - Date.parse(prev.recorded_at) > 30_000 ||
      turf.distance([prev.lon, prev.lat], [p.lon, p.lat], { units: 'meters' }) > 100)) pieces.push([]);
  pieces.at(-1)!.push([p.lat, p.lon]);
}
L.polyline(pieces, { weight: 4, opacity: 0.8 }).addTo(historyLayer);
```

Note: Supabase returns at most 1000 rows per request by default; a trip longer than \~1.5 h needs paging with `.range()`.

**Test before moving on**

- [ ] Two phones recording at once: each sees the other's dot move within \~10 s
- [ ] A recorded trip redraws identically from history after reloading the page
- [ ] A trip with an airplane-mode gap shows a break, not a straight line across
- [ ] Map stays smooth (no visible lag) with 3 trips of 30 minutes shown together

## Step 6: notes on the road (\~1.5 h)

A note is a point plus a category, optional text, severity and photo. The main design rule: GPS gives the starting position, the person fixes it by dragging the pin, because 5–15 m of GPS error can put a note on the wrong side of the street.

**Flow**

1. Two ways to start: a big "Note here" button (starts at the current GPS position) or a long-press on the map (starts where pressed). Leaflet's `contextmenu` event fires on long-press on touch screens.
2. A draggable marker appears plus a bottom sheet with: category buttons (big, one tap), severity 1–3, a text field, "Add photo".
3. Photo: `<input type="file" accept="image/*" capture="environment">` opens the camera. Resize in the browser to max 1600 px, JPEG quality 0.8 (draw on a canvas, `canvas.toBlob`), typically 200–400 KB.
4. Save: read the marker's final position, build the row with a new UUID, queue the photo (if any) and the note (step 4), close the sheet, show the pin immediately.
5. Tap a pin: popup with category, text, author, time, photo thumbnail (from Storage public or signed URL).

```ts
// notes.ts — save
async function saveNote(form: NoteForm, marker: L.Marker) {
  const { lat, lng } = marker.getLatLng();
  const id = crypto.randomUUID();
  let photo_path: string | null = null;
  if (form.photo) {
    const blob = await resizeImage(form.photo, 1600, 0.8);
    photo_path = `${userId}/${id}.jpg`;
    await queue.add('photos', { path: photo_path, blob });
  }
  await queue.add('notes', { id, trip_id: currentTripId, geom: `SRID=4326;POINT(${lng} ${lat})`,
                             category: form.category, severity: form.severity, body: form.text, photo_path });
  map.addNotePin({ id, lat, lon: lng, ...form });
  queue.flush();
}
```

**Accessibility of the app itself** (the users may be wheelchair users, older people, or people with low vision): buttons at least 48 px, high contrast, text labels next to icons, works one-handed, no gesture is the only way to do something (long-press always has the "Note here" button as an alternative).

**Test before moving on**

- [ ] Note with photo saved on iPhone appears with its photo on the Android phone within 5 s
- [ ] Note saved in airplane mode appears for others after reconnecting, photo included
- [ ] Dragging the pin 20 m before saving stores the dragged position, not the GPS one
- [ ] Photo upload of a 12 MP camera image is under 500 KB in Storage

## Step 7: export (\~45 min)

One "Export" button on the trip list downloads two files, built in the browser from the same queries the map uses.

| File | Contents | Opens in |
| --- | --- | --- |
| `able-notes-YYYY-MM-DD.geojson` | Every note as a Point feature (category, severity, text, author, time, photo URL) plus every trip as a MultiLineString (split at gaps, as on the map) | geojson.io, QGIS, any web map |
| `trip-<id>.gpx` | One trip as a GPX track with timestamps; notes as waypoints | OsmAnd, Strava, Garmin, Google Earth |
| `able-notes.csv` (optional) | One row per note: lat, lon, category, severity, text, time, photo URL | Excel, Google Sheets |

GeoJSON uses `[longitude, latitude]` order; GPX uses `lat`/`lon` attributes. Mixing these up puts Sofia in Saudi Arabia, so the export test checks it.

Download in the browser: build the text, wrap it in a `Blob`, create an `<a download>` link and click it. On iPhone this opens the share sheet, which is fine.

**Test before moving on**

- [ ] The GeoJSON dropped on geojson.io shows the notes and lines in Sofia, in the right streets
- [ ] The GPX imports into OsmAnd (or another GPS app) and shows the track with correct times
- [ ] The CSV opens in a spreadsheet with Cyrillic text intact (write a UTF-8 BOM at the start)

## Build order for day 1

About 9 hours of building plus the field test. Each block ends with its test; do not start the next block while the current test fails.

| Time | Build | Test at the end |
| --- | --- | --- |
| 09:00–09:45 | Step 1: Supabase project, Vite app, Netlify deploy, empty map | Link opens on both phones |
| 09:45–10:30 | Step 2: SQL schema, rules, bucket, anonymous sign-in + name prompt | Insert/read in SQL editor; foreign write refused |
| 10:30–12:00 | Step 3: Start/Stop, wake lock, `watchPosition`, filter, status bar | DevTools Sensors + replay script; 10-min walk with screen on |
| 12:00–12:30 | Lunch — and walk with the phone to see real GPS behaviour | Note how accuracy changes near buildings |
| 12:30–13:30 | Step 4: queue + flush + retry | Airplane-mode test, no duplicates |
| 13:30–15:00 | Step 5: live line, others' dots, trip list, history | Two phones see each other; history redraws |
| 15:00–16:30 | Step 6: notes, draggable pin, photo, popups | Note with photo appears on the other phone |
| 16:30–17:15 | Step 7: export | geojson.io + GPS app import |
| 17:15–17:45 | PWA manifest + icon, polish the status bar, big-button pass | Add to home screen works on both phones |
| 17:45–19:00 | Field test (next section) | Definition of done checklist |

**How to vibe-code each block:** give Claude Code the section of this doc for that step (schema, rules, code sketch, tests) as the prompt, ask it to write the tests or test page first, and deploy after every block so the phones always run the latest version.

**Buffer:** if behind schedule, cut in this order: CSV export → others' live dots → photo on notes. Never cut the offline queue; it is what keeps the data.

## Field test in Sofia (\~1 h)

Two people, two phones (one Android, one iPhone), one laptop watching the shared map. Pick a loop of about 1.5 km that mixes the cases GPS struggles with.

**Route ingredients**

- A wide boulevard (open sky — the baseline)
- A narrow street between taller buildings (urban canyon)
- A pedestrian underpass or metro entrance (signal loss → gap + offline queue)
- A crossing with a known high curb or missing ramp (a real note to pin)
- A park path (trees, but open)

**Script**

1. Both start a trip at the same spot; walk together for the first half.
2. Pin the same obstacle from both phones without dragging, then a second note each with dragging — compare how far apart the undragged pins land.
3. Turn on airplane mode on one phone for 2 minutes in the middle.
4. Split up for the second half; the laptop person checks that both dots move.
5. Stop, export, open the GeoJSON on geojson.io.

**Record afterwards** (fill in on the day)

| Measure | Android | iPhone |
| --- | --- | --- |
| Typical accuracy on the boulevard (m) |  |  |
| Typical accuracy in the narrow street (m) |  |  |
| Distance between the two undragged pins of the same obstacle (m) |  |  |
| Longest gap outside the underpass (s) |  |  |
| Points lost in airplane mode |  |  |
| Battery used in 1 h (%) |  |  |
| Did the screen stay on the whole time? |  |  |

These numbers decide the filter thresholds and whether stage 2 snapping is urgent.

## Risks and open questions

| Risk | Effect | What we do |
| --- | --- | --- |
| iPhone stops GPS when the screen dims or Safari is backgrounded | Gaps in the track | Wake lock + tell testers to keep the app in front; stage 1 fixes it properly |
| Wake lock not supported on an older phone | Screen locks, tracking stops | Status bar warns; testers set auto-lock to "Never" for the test |
| GPS 10–30 m off in narrow streets | Lines through buildings, notes on wrong side | Accuracy filter, draggable pins; snapping in stage 2 |
| OSM tile server usage policy | Tiles blocked if we load too many | Fine for a demo; switch to MapTiler/Stadia free plan before the pilot |
| Anonymous sign-in on a new phone or cleared browser | User loses access to their old trips | Acceptable for the demo; email login in stage 2 |
| Location data of disabled people is personal data | GDPR obligations | Demo data only from the team; consent text and a delete button before the pilot |

**Open questions**

- [ ] Which note categories matter most to the people we talk to? (replace the demo list)
- [ ] Should others see a walker's live position, or only finished trips? (privacy for the pilot)
- [ ] Who owns the Supabase and Netlify accounts — personal or a project account?
- [ ] Does anyone on the team have an Apple Developer account (needed in stage 3)?
- [ ] Do we want the data to end up in OpenStreetMap or Call Sofia, and in what form?
