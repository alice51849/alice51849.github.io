import assert from 'node:assert/strict';
import test from 'node:test';

import {
  GUIDE_CATALOG_URL,
  ROOT_SLUGS,
  validateGuideRoster,
  verifiedGuideApps,
  verifiedGuideIds,
} from './sync-apps.mjs';


function app(id = '1234567890', key = `sample${id}`) {
  return {
    key,
    app_store_id: id,
    app_store_url: `https://apps.apple.com/us/app/id${id}`,
    verified_live: true,
  };
}

function response(document, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    async json() {
      return document;
    },
  };
}

test('verified Guide IDs are accepted exactly once', async () => {
  const document = {
    locale: 'en-US',
    record_count: 2,
    apps: [app('1234567890'), app('2345678901')],
  };
  const ids = await verifiedGuideIds(async (url, options) => {
    assert.equal(url, GUIDE_CATALOG_URL);
    assert.equal(options.headers.Accept, 'application/json');
    return response(document);
  });
  assert.deepEqual([...ids].sort(), ['1234567890', '2345678901']);
});

test('verified Guide apps preserve the canonical roster key', async () => {
  const document = {
    locale: 'en-US',
    record_count: 2,
    apps: [
      app('1234567890', 'sampleone'),
      app('2345678901', 'sampletwo'),
    ],
  };
  const apps = await verifiedGuideApps(async () => response(document));
  assert.deepEqual(
    [...apps.entries()],
    [
      ['1234567890', 'sampleone'],
      ['2345678901', 'sampletwo'],
    ],
  );
});

test('root slug contract must cover the exact verified Guide roster', () => {
  const apps = new Map(
    Object.keys(ROOT_SLUGS).map((key, index) => [
      String(7000000000 + index),
      key,
    ]),
  );
  assert.doesNotThrow(() => validateGuideRoster(apps));
  apps.delete(apps.keys().next().value);
  assert.throws(() => validateGuideRoster(apps), /Guide\/root roster differs/);
});

test('incomplete or unverified Guide catalogs fail closed', async () => {
  const cases = [
    { locale: 'fr-FR', record_count: 1, apps: [app()] },
    { locale: 'en-US', record_count: 2, apps: [app()] },
    {
      locale: 'en-US',
      record_count: 1,
      apps: [{ ...app(), verified_live: false }],
    },
    {
      locale: 'en-US',
      record_count: 1,
      apps: [{ ...app(), app_store_url: 'https://example.com/app' }],
    },
    {
      locale: 'en-US',
      record_count: 2,
      apps: [app(), app()],
    },
  ];
  for (const document of cases) {
    await assert.rejects(
      verifiedGuideIds(async () => response(document)),
    );
  }
});

test('Guide transport errors do not fall back to ASC-only publication', async () => {
  await assert.rejects(
    verifiedGuideIds(async () => response({}, { ok: false, status: 503 })),
    /Guide catalog 503/,
  );
});
