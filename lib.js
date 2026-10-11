/* Pompa Giusta: funzioni pure (formati, medie, distanze, percorso, lettura dei CSV).
   Funziona nel browser e in Node (per i test). */
(function (root) {
'use strict';
const PG = {};
let PROV = {}, NAMEIDX = {};

PG.norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase()
  .replace(/[^A-Z ]/g, ' ').replace(/\s+/g, ' ').trim();

PG.setProvinces = function (list) {
  PROV = {}; NAMEIDX = {};
  list.forEach(([c, n, r]) => { PROV[c] = { name: n, reg: r }; NAMEIDX[PG.norm(n)] = c; });
  [['FORLI CESENA', 'FC'], ['MASSA CARRARA', 'MS'], ['REGGIO NELL EMILIA', 'RE'],
   ['REGGIO DI CALABRIA', 'RC'], ['VALLE D AOSTA', 'AO'], ['BOLZANO BOZEN', 'BZ']]
    .forEach(([a, b]) => { NAMEIDX[a] = b; });
};
PG.prov = c => PROV[c] || null;
PG.provName = c => (PROV[c] ? PROV[c].name : c);
PG.region = c => (PROV[c] ? PROV[c].reg : c);
PG.sigla = function (raw) {
  const r = String(raw || '').trim(), u = r.toUpperCase();
  if (u.length === 2 && PROV[u]) return u;
  return NAMEIDX[PG.norm(r)] || u;
};

const ACR = new Set(['ip', 'q8', 'gpl', 'srl', 'spa', 'sas', 'snc', 'gnl', 'cng']);
PG.title = s => String(s || '').toLowerCase()
  .replace(/(^|[\s'’\-.(])([a-zà-ÿ])/g, (m, a, b) => a + b.toUpperCase());
PG.brandTitle = s => String(s || '').split(/\s+/).filter(Boolean)
  .map(w => (ACR.has(w.toLowerCase()) ? w.toUpperCase() : PG.title(w))).join(' ');

/* ---------- formati ---------- */
PG.fmtP = v => v.toFixed(3).replace('.', ',');
PG.fmtE = v => v.toLocaleString('it-IT', { style: 'currency', currency: 'EUR' });
PG.fmtC = d => (d > 0.00005 ? '+' : d < -0.00005 ? '−' : '') + Math.abs(d * 100).toFixed(1).replace('.', ',') + ' c/L';
PG.fmtKm = k => (k < 10 ? k.toFixed(1) : Math.round(k).toString()).replace('.', ',') + ' km';
PG.priceDate = (iso, ageDays) => { // data in cui il gestore ha comunicato il prezzo (gg/mm)
  const t = new Date(iso + 'T12:00:00Z'); t.setUTCDate(t.getUTCDate() - ageDays);
  return String(t.getUTCDate()).padStart(2, '0') + '/' + String(t.getUTCMonth() + 1).padStart(2, '0');
};
PG.fmtD = iso => { if (!iso) return ''; const [y, m, d] = iso.split('-'); return d + '/' + m + '/' + y; };

/* ---------- medie ---------- */
PG.computeAvg = function (stations) {
  const o = {};
  stations.forEach(s => {
    if (s.hw) return;
    const reg = PG.region(s.prov);
    for (const k in s.p) {
      const e = o[k] || (o[k] = { sum: 0, n: 0, r: {} });
      e.sum += s.p[k]; e.n++;
      const r = e.r[reg] || (e.r[reg] = { sum: 0, n: 0 });
      r.sum += s.p[k]; r.n++;
    }
  });
  const out = {};
  for (const k in o) {
    out[k] = { ALL: o[k].sum / o[k].n, r: {} };
    for (const g in o[k].r) out[k].r[g] = o[k].r[g].sum / o[k].r[g].n;
  }
  return out;
};

/* ---------- distanze e percorso ---------- */
PG.haversine = function (a, b, c, d) {
  const R = 6371, t = Math.PI / 180;
  const x = Math.sin((c - a) * t / 2) ** 2 + Math.cos(a * t) * Math.cos(c * t) * Math.sin((d - b) * t / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
};

/* coords: [[lon,lat],...] (GeoJSON). Restituisce punti [lat,lon,kmDallaPartenza] ogni stepKm. */
PG.resample = function (coords, stepKm) {
  if (!coords.length) return { pts: [], total: 0 };
  const out = [[coords[0][1], coords[0][0], 0]];
  let carry = 0, total = 0;
  for (let i = 1; i < coords.length; i++) {
    const [lo0, la0] = coords[i - 1], [lo1, la1] = coords[i];
    const seg = PG.haversine(la0, lo0, la1, lo1);
    if (seg === 0) continue;
    let pos = 0;
    while (carry + (seg - pos) >= stepKm) {
      pos += stepKm - carry;
      const f = pos / seg;
      out.push([la0 + (la1 - la0) * f, lo0 + (lo1 - lo0) * f, total + pos]);
      carry = 0;
    }
    carry += seg - pos;
    total += seg;
  }
  const last = coords[coords.length - 1];
  out.push([last[1], last[0], total]);
  return { pts: out, total };
};

/* Distributori entro maxKm (in linea d'aria) dal percorso. */
PG.corridor = function (stations, key, pts, maxKm) {
  if (!pts.length) return [];
  let minLa = 90, maxLa = -90, minLo = 180, maxLo = -180;
  pts.forEach(p => {
    if (p[0] < minLa) minLa = p[0]; if (p[0] > maxLa) maxLa = p[0];
    if (p[1] < minLo) minLo = p[1]; if (p[1] > maxLo) maxLo = p[1];
  });
  const mLa = maxKm / 111, mLo = maxKm / (111 * Math.cos(((minLa + maxLa) / 2) * Math.PI / 180));
  const out = [];
  for (const s of stations) {
    if (s.lat == null || s.p[key] == null) continue;
    if (s.lat < minLa - mLa || s.lat > maxLa + mLa || s.lon < minLo - mLo || s.lon > maxLo + mLo) continue;
    const kx = 111.32 * Math.cos(s.lat * Math.PI / 180);
    let best = Infinity, bi = 0;
    for (let i = 0; i < pts.length; i++) {
      const dx = (pts[i][1] - s.lon) * kx, dy = (pts[i][0] - s.lat) * 111.2;
      const d2 = dx * dx + dy * dy;
      if (d2 < best) { best = d2; bi = i; }
    }
    const d = Math.sqrt(best);
    if (d <= maxKm) out.push({ s, d, km: pts[bi][2] });
  }
  return out;
};

/* Distributori entro radiusKm da un punto. */
PG.near = function (stations, key, lat, lon, radiusKm) {
  const mLa = radiusKm / 111, mLo = radiusKm / (111 * Math.cos(lat * Math.PI / 180));
  const out = [];
  for (const s of stations) {
    if (s.lat == null || s.p[key] == null) continue;
    if (Math.abs(s.lat - lat) > mLa || Math.abs(s.lon - lon) > mLo) continue;
    const d = PG.haversine(lat, lon, s.lat, s.lon);
    if (d <= radiusKm) out.push({ s, d });
  }
  return out;
};

/* Deviazione stimata su strada (andata e ritorno) data la distanza in linea d'aria. */
PG.detour = d => (d < 0.15 ? 0 : 2 * d * 1.4);
/* Costo del pieno comprensivo del carburante consumato per la deviazione. */
PG.cost = (price, litri, consumo, detourKm) => litri * price + detourKm * consumo / 100 * price;

/* ---------- lettura dei CSV del MIMIT (caricamento manuale di riserva) ---------- */
function splitLine(l, sep) {
  if (sep === '|' || l.indexOf('"') < 0) return l.split(sep);
  const o = []; let c = '', q = false;
  for (const ch of l) {
    if (ch === '"') q = !q;
    else if (ch === sep && !q) { o.push(c); c = ''; }
    else c += ch;
  }
  o.push(c); return o;
}
PG.parseTable = function (text) {
  const lines = text.split(/\r?\n/);
  const h = lines.findIndex(l => /idimpianto/i.test(l));
  if (h < 0) throw new Error("Non trovo l'intestazione con idImpianto: il file non sembra un dato del MIMIT.");
  const head = lines[h];
  const sep = head.includes('|') ? '|' : head.includes(';') ? ';' : ',';
  const cols = splitLine(head, sep).map(s => s.trim().toLowerCase());
  const col = n => { let i = cols.findIndex(c => c === n); return i >= 0 ? i : cols.findIndex(c => c.includes(n)); };
  return { cols, col, sep, meta: lines.slice(0, h).join(' '), lines, start: h + 1 };
};
PG.buildAnag = function (t) {
  const ci = { id: t.col('idimpianto'), brand: t.col('bandiera'), tipo: t.col('tipo'), name: t.col('nome'),
    addr: t.col('indirizzo'), com: t.col('comune'), prov: t.col('provincia'), lat: t.col('latitudine'), lon: t.col('longitudine') };
  const out = [];
  for (let i = t.start; i < t.lines.length; i++) {
    const l = t.lines[i]; if (!l.trim()) continue;
    const c = splitLine(l, t.sep); const id = (c[ci.id] || '').trim(); if (!id) continue;
    let lat = parseFloat(String(c[ci.lat] || '').replace(',', '.')), lon = parseFloat(String(c[ci.lon] || '').replace(',', '.'));
    if (!(lat > 35 && lat < 48 && lon > 6 && lon < 19)) { lat = null; lon = null; }
    const pv = PG.sigla(c[ci.prov]);
    out.push({ id, brand: PG.brandTitle(c[ci.brand]) || 'Altro', name: (c[ci.name] || '').trim() || 'Impianto ' + id,
      addr: (c[ci.addr] || '').trim(), comune: PG.title((c[ci.com] || '').trim()), prov: pv,
      hw: /autostrad/i.test(c[ci.tipo] || ''), lat, lon, s: [] });
  }
  return out;
};
function parseDT(s) {
  const m = String(s || '').match(/(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0)).getTime();
  const i = Date.parse(s); return isNaN(i) ? null : i;
}
PG.buildPrices = function (t) {
  const ci = { id: t.col('idimpianto'), d: t.col('desccarburante') >= 0 ? t.col('desccarburante') : t.col('carburante'),
    p: t.col('prezzo'), s: t.col('isself'), dt: t.col('dtcomu') };
  let ref = null;
  const mm = t.meta.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (mm) ref = new Date(+mm[1], +mm[2] - 1, +mm[3], 23, 59).getTime();
  else { const m2 = t.meta.match(/(\d{2})\/(\d{2})\/(\d{4})/); if (m2) ref = new Date(+m2[3], +m2[2] - 1, +m2[1], 23, 59).getTime(); }
  const rows = []; let maxDt = 0;
  for (let i = t.start; i < t.lines.length; i++) {
    const l = t.lines[i]; if (!l.trim()) continue;
    const c = splitLine(l, t.sep);
    const d = (c[ci.d] || '').trim().toLowerCase();
    const k = d === 'benzina' ? 'B' : d === 'gasolio' ? 'D' : d === 'gpl' ? 'G' : d === 'metano' ? 'M' : null; if (!k) continue;
    const pr = parseFloat(String(c[ci.p]).replace(',', '.')); if (!(pr > 0.4 && pr < 5)) continue;
    const sv = String(c[ci.s]).trim().toLowerCase();
    const dt = parseDT(c[ci.dt]); if (dt && dt > maxDt) maxDt = dt;
    rows.push([c[ci.id].trim(), k + ((sv === '1' || sv === 'true' || sv === 'si') ? 1 : 0), pr, dt]);
  }
  if (!ref) ref = maxDt || Date.now();
  const map = {}; let stale = 0;
  rows.forEach(([id, k, pr, dt]) => {
    if (dt && (ref - dt) / 864e5 > 8) { stale++; return; }
    const o = map[id] || (map[id] = {}); if (o[k] == null || pr < o[k]) o[k] = pr;
  });
  const dd = new Date(ref);
  const date = dd.getFullYear() + '-' + String(dd.getMonth() + 1).padStart(2, '0') + '-' + String(dd.getDate()).padStart(2, '0');
  return { map, date, stale };
};

if (typeof module !== 'undefined' && module.exports) module.exports = PG; else root.PG = PG;
})(typeof window !== 'undefined' ? window : globalThis);
