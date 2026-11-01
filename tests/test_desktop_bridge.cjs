'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const bridgeSource = fs.readFileSync(path.join(__dirname, '../web/desktop.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const apiSource = appSource.slice(appSource.indexOf('async function api('), appSource.indexOf('function setBusy('));

function runtime({protocol = 'file:', transport = true, nativeThrows = false} = {}) {
  const timers = new Map(), scripts = [], calls = [];
  let timerId = 0, response;
  const native = {
    response: {connect: callback => { response = callback; }},
    request: (...args) => { if (nativeThrows) throw new Error('Native connection failed.'); calls.push(args); }
  };
  const context = {
    location: {protocol},
    document: {createElement: () => ({}), head: {appendChild: script => scripts.push(script)}},
    setTimeout: (callback, delay) => { timers.set(++timerId, {callback, delay}); return timerId; },
    clearTimeout: id => timers.delete(id),
    QWebChannel: function (_transport, callback) { callback({objects: {desktopBridge: native}}); }
  };
  context.window = context;
  if (transport) context.qt = {webChannelTransport: {}};
  vm.createContext(context);
  vm.runInContext(bridgeSource, context);
  return {
    context, timers, scripts, calls, bridge: context.SurveyDesktop,
    load: () => scripts[0].onload(),
    respond: (id, data) => response(id, JSON.stringify(data)),
    rawResponse: (id, raw) => response(id, raw),
    expire: delay => {
      const entry = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, `Expected a ${delay} ms timer`);
      timers.delete(entry[0]);
      entry[1].callback();
    },
    api: () => { vm.runInContext(apiSource + '\nwindow.testApi = api;', context); return context.testApi; }
  };
}

test('browser mode starts without Qt resources and keeps HTTP requests', async () => {
  const r = runtime({protocol: 'http:', transport: false});
  assert.equal(r.bridge.isDesktop, false);
  assert.equal(await r.bridge.ready, null);
  assert.equal(r.scripts.length, 0);
  assert.equal(r.timers.size, 0);
  const fetched = [];
  r.context.fetch = async (...args) => { fetched.push(args); return {ok: true, json: async () => ({value: 7})}; };
  assert.deepEqual(await r.api()('/api/solve', {budget: 3}), {value: 7});
  assert.equal(fetched[0][1].method, 'POST');
  assert.equal(fetched[0][1].body, '{"budget":3}');
  await assert.rejects(r.bridge.request('/api/health'), /browser mode/);
});

test('desktop requests wait for connection and match out-of-order responses', async () => {
  const r = runtime();
  assert.equal(r.bridge.isDesktop, true);
  assert.equal(r.scripts[0].src, 'qrc:///qtwebchannel/qwebchannel.js');
  const first = r.bridge.request('/api/scenario?seed=42');
  assert.equal(r.calls.length, 0);
  r.load();
  await r.bridge.ready;
  const second = r.bridge.request('/api/solve', {budget: 3});
  await Promise.resolve();
  assert.equal(r.calls.length, 2);
  assert.equal(r.calls[0][2], 'null');
  assert.equal(r.calls[1][2], '{"budget":3}');
  assert.notEqual(r.calls[0][0], r.calls[1][0]);
  r.respond(r.calls[1][0], {ok: true, data: {objective: 0.02}});
  r.respond(r.calls[0][0], {ok: true, data: {seed: 42}});
  assert.equal((await first).seed, 42);
  assert.equal((await second).objective, 0.02);
  assert.equal(r.timers.size, 0);
});

test('save uses a native dialog payload and cancellation resolves normally', async () => {
  const r = runtime(); r.load();
  const saving = r.bridge.saveJson('{"seed":42}', 'run.json');
  await Promise.resolve();
  assert.equal(r.calls[0][1], '/desktop/save');
  assert.deepEqual(JSON.parse(r.calls[0][2]), {content: '{"seed":42}', filename: 'run.json'});
  r.respond(r.calls[0][0], {ok: true, data: {saved: false}});
  assert.equal((await saving).saved, false);
  assert.equal(r.timers.size, 0);
});

test('native errors and malformed responses reject and clean request timers', async () => {
  const r = runtime(); r.load();
  const failed = r.bridge.request('/api/solve', {});
  await Promise.resolve();
  r.respond(r.calls[0][0], {ok: false, error: 'No solver is available.'});
  await assert.rejects(failed, /No solver is available/);
  const invalid = r.bridge.request('/api/health', null);
  await Promise.resolve();
  assert.equal(r.calls[1][2], 'null');
  r.rawResponse(r.calls[1][0], '{"unexpected":true}');
  await assert.rejects(invalid, /Invalid response/);
  assert.equal(r.timers.size, 0);
});

test('requests time out after 120 seconds and late replies are ignored', async () => {
  const r = runtime(); r.load();
  const waiting = r.bridge.request('/api/frontier', {});
  await Promise.resolve();
  r.expire(120000);
  await assert.rejects(waiting, /120 seconds/);
  assert.equal(r.timers.size, 0);
  assert.doesNotThrow(() => r.respond(r.calls[0][0], {ok: true, data: {late: true}}));
});

test('synchronous native failure also cleans the request timer', async () => {
  const r = runtime({nativeThrows: true}); r.load();
  await assert.rejects(r.bridge.request('/api/health'), /Native connection failed/);
  assert.equal(r.timers.size, 0);
});

test('missing desktop transport fails clearly without HTTP fallback', async () => {
  const r = runtime({transport: false});
  let fetches = 0;
  r.context.fetch = async () => { fetches++; throw new Error('Unexpected fetch'); };
  const calling = r.api()('/api/health');
  r.expire(10000);
  await assert.rejects(calling, /desktop connection did not start/);
  assert.equal(r.scripts.length, 0);
  assert.equal(fetches, 0);
  assert.equal(r.timers.size, 0);
});

test('missing desktop.js never sends file API requests over fetch', async () => {
  const context = {window: {location: {protocol: 'file:'}}, fetch: async () => { throw new Error('Unexpected fetch'); }};
  vm.createContext(context);
  vm.runInContext(apiSource + '\nwindow.testApi = api;', context);
  await assert.rejects(context.window.testApi('/api/health'), /desktop connection is unavailable/);
});

test('desktop api dispatch uses the native transport', async () => {
  const r = runtime(); r.load();
  r.context.fetch = async () => { throw new Error('Unexpected fetch'); };
  const calling = r.api()('/api/solve', {budget: 2});
  await Promise.resolve(); await Promise.resolve();
  r.respond(r.calls[0][0], {ok: true, data: {solver: 'SCIP'}});
  assert.equal((await calling).solver, 'SCIP');
});
