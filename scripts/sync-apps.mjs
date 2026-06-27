#!/usr/bin/env node
/**
 * sync-apps.mjs — keep assets/data.js in sync with the studio's live App Store apps.
 *
 * Lists every app on the App Store Connect account, finds the ones that are live on
 * the store but NOT yet on the site, fetches their 4-language name / subtitle / blurb
 * and icon, then APPENDS them to assets/data.js (existing curated entries are left
 * byte-for-byte untouched). Designed to run daily from a GitHub Action.
 *
 * Env: ASC_KEY_ID, ASC_ISSUER_ID, ASC_PRIVATE_KEY (.p8 contents). DRY_RUN=1 to preview.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const KEY_ID = process.env.ASC_KEY_ID;
const ISSUER = process.env.ASC_ISSUER_ID;
const P8     = process.env.ASC_PRIVATE_KEY;
const DRY    = process.env.DRY_RUN === '1';

const ROOT  = process.cwd();
const DATA  = path.join(ROOT, 'assets', 'data.js');
const ICONS = path.join(ROOT, 'assets', 'icons');
const SHOTS = path.join(ROOT, 'assets', 'shots');
const TARGET_LOCALES = { en: ['en-US', 'en-GB', 'en-AU'], zh: ['zh-Hant', 'zh-Hans'], ja: ['ja'], ko: ['ko'] };

if (!KEY_ID || !ISSUER || !P8) { console.error('✗ Missing ASC_KEY_ID / ASC_ISSUER_ID / ASC_PRIVATE_KEY'); process.exit(1); }

const b64url = (b) => Buffer.from(b).toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
function mintToken() {
  const header = { alg: 'ES256', kid: KEY_ID, typ: 'JWT' };
  const now = Math.floor(Date.now() / 1000);
  const payload = { iss: ISSUER, iat: now, exp: now + 900, aud: 'appstoreconnect-v1' };
  const input = b64url(JSON.stringify(header)) + '.' + b64url(JSON.stringify(payload));
  const sig = crypto.createSign('SHA256').update(input).sign({ key: P8, dsaEncoding: 'ieee-p1363' });
  return input + '.' + b64url(sig);
}
const TOKEN = mintToken();

async function api(url) {
  const full = url.startsWith('http') ? url : 'https://api.appstoreconnect.apple.com' + url;
  const r = await fetch(full, { headers: { Authorization: 'Bearer ' + TOKEN } });
  if (!r.ok) throw new Error(`ASC ${r.status} ${url} :: ${(await r.text()).slice(0, 240)}`);
  return r.json();
}
async function itunesLookup(id) {
  try {
    const r = await fetch(`https://itunes.apple.com/lookup?id=${id}&country=tw`);
    const j = await r.json();
    return (j.results && j.results[0]) || null;
  } catch { return null; }
}
// 撈 App Store iPhone hero 截圖,下載到 assets/shots/{slug}.jpg
async function fetchHeroShot(appleId, slug) {
  try {
    const vers = await api(`/v1/apps/${appleId}/appStoreVersions?limit=1`);
    if (!vers.data[0]) return;
    const locs = await api(`/v1/appStoreVersions/${vers.data[0].id}/appStoreVersionLocalizations`);
    const loc = locs.data.find((l) => l.attributes.locale === 'en-US') || locs.data[0];
    if (!loc) return;
    const sets = await api(`/v1/appStoreVersionLocalizations/${loc.id}/appScreenshotSets`);
    const iph = sets.data.find((s) => /IPHONE/.test(s.attributes.screenshotDisplayType));
    if (!iph) return;
    const shots = await api(`/v1/appScreenshotSets/${iph.id}/appScreenshots`);
    const ia = shots.data.map((s) => s.attributes.imageAsset).find(Boolean);
    if (!ia) return;
    const w = 600, h = Math.round((w * ia.height) / ia.width);
    const url = ia.templateUrl.replace('{w}', w).replace('{h}', h).replace('{f}', 'jpg');
    const r = await fetch(url); const buf = Buffer.from(await r.arrayBuffer());
    fs.writeFileSync(path.join(SHOTS, slug + '.jpg'), buf);
    console.log(`  📸 shot ${slug}.jpg`);
  } catch (e) { console.log(`  (no shot for ${slug}: ${e.message})`); }
}
const pick = (list, locales, field) => {
  for (const loc of locales) { const hit = list.find((x) => x.attributes.locale === loc); if (hit && hit.attributes[field]) return hit.attributes[field]; }
  const any = list.find((x) => x.attributes[field]); return any ? any.attributes[field] : '';
};
const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'app';
const trim = (s, n = 116) => { s = (s || '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };

async function main() {
  const dataText = fs.readFileSync(DATA, 'utf8');
  const existingIds = new Set([...dataText.matchAll(/id(\d{6,})/g)].map((m) => m[1]));
  const existingSlugs = new Set([...dataText.matchAll(/"slug":\s*"([^"]+)"/g)].map((m) => m[1]));

  // 1) list every app on the account
  const apps = [];
  let next = '/v1/apps?limit=200&fields[apps]=name,bundleId';
  while (next) { const j = await api(next); apps.push(...j.data); next = j.links && j.links.next; }
  console.log(`• Account has ${apps.length} apps; site already lists ${existingIds.size}.`);

  // 2) find live apps not yet on the site
  const additions = [];
  for (const app of apps) {
    const appleId = app.id;
    if (existingIds.has(appleId)) continue;
    const it = await itunesLookup(appleId);
    if (!it) { console.log(`  – ${app.attributes.name} (${appleId}) not live yet — skipped`); continue; }

    let nameLoc = [], verLoc = [];
    try {
      const infos = await api(`/v1/apps/${appleId}/appInfos?limit=1`);
      if (infos.data[0]) nameLoc = (await api(`/v1/appInfos/${infos.data[0].id}/appInfoLocalizations?limit=50`)).data;
    } catch (e) { console.log('   (name localizations unavailable)', e.message); }
    try {
      const vers = await api(`/v1/apps/${appleId}/appStoreVersions?limit=1&fields[appStoreVersions]=versionString`);
      if (vers.data[0]) verLoc = (await api(`/v1/appStoreVersions/${vers.data[0].id}/appStoreVersionLocalizations?limit=50`)).data;
    } catch (e) { console.log('   (store localizations unavailable)', e.message); }

    const name = {}, sub = {}, blurb = {};
    for (const [key, locales] of Object.entries(TARGET_LOCALES)) {
      name[key]  = pick(nameLoc, locales, 'name') || it.trackName || app.attributes.name;
      sub[key]   = pick(nameLoc, locales, 'subtitle') || '';
      blurb[key] = trim(pick(verLoc, locales, 'promotionalText') || pick(verLoc, locales, 'description') || it.description || '');
    }
    const genres = (it.genres || []).concat(it.primaryGenreName || []);
    const cat = genres.some((g) => /education|kids|family/i.test(g)) ? 'kids' : 'tools';
    const badge = (it.price > 0) ? 'Pro' : (/\blite\b/i.test(it.trackName) ? 'Lite' : (/\bpro\b/i.test(it.trackName) ? 'Pro' : ''));  // paid apps → Pro
    let slug = slugify(it.trackName || app.attributes.name);
    while (existingSlugs.has(slug)) slug += '-' + appleId.slice(-3);
    existingSlugs.add(slug);
    const iconUrl = it.artworkUrl512 || it.artworkUrl100 || it.artworkUrl60;

    additions.push({ entry: { slug, cat, icon: `assets/icons/${slug}.png`, url: it.trackViewUrl || `https://apps.apple.com/tw/app/id${appleId}`, badge, name, sub, blurb, shot: null }, iconUrl, appleId });
    console.log(`  ✚ NEW: ${name.en}  [${cat}${badge ? '/' + badge : ''}]  → ${slug}`);
  }

  if (!additions.length) { console.log('✓ Nothing new — site is up to date.'); return; }
  if (DRY) { console.log(`\n[DRY RUN] Would add ${additions.length} app(s). No files written.`); console.log(JSON.stringify(additions.map((a) => a.entry), null, 1)); return; }

  // 3) download icons (high quality)
  fs.mkdirSync(ICONS, { recursive: true });
  for (const a of additions) {
    const hi = a.iconUrl.replace(/\/\d+x\d+bb\.(png|jpg|jpeg|webp)/i, '/1024x1024bb.png');
    const r = await fetch(hi); const buf = Buffer.from(await r.arrayBuffer());
    fs.writeFileSync(path.join(ICONS, a.entry.slug + '.png'), buf);
    console.log(`  ⬇ icon ${a.entry.slug}.png (${(buf.length / 1024) | 0} KB)`);
  }

  // 3b) download App Store hero screenshots for the new apps
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const a of additions) {
    await fetchHeroShot(a.appleId, a.entry.slug);
  }

  // 4) append entries to data.js, leaving existing curated entries untouched
  const block = additions.map((a) => JSON.stringify(a.entry, null, 1).replace(/^/gm, ' ')).join(',\n');
  const updated = dataText.replace(/\n\];\s*$/, ',\n' + block + '\n];\n');
  fs.writeFileSync(DATA, updated);
  console.log(`✓ Added ${additions.length} app(s) to assets/data.js`);
}

main().catch((e) => { console.error('✗', e.message); process.exit(1); });
