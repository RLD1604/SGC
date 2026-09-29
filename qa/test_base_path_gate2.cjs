'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'public', 'base-path.js'), 'utf8');

function harness(base) {
  const calls = [];
  const response = {
    headers: {get: name => name.toLowerCase() === 'content-type' ? 'application/json' : null},
    json: async () => ({photo: {src: '/api/media/' + 'a'.repeat(64)}}),
  };
  const nativeFetch = async (url, options) => { calls.push({url, options}); return response; };
  const window = {fetch: nativeFetch};
  const context = {
    window,
    document: {querySelector: () => base ? {content: base} : null},
    URL,
    Headers,
    Set,
    Object,
    Array,
    JSON,
  };
  vm.runInNewContext(source, context, {filename: 'base-path.js'});
  return {window, calls};
}

(async () => {
  const mounted = harness('/SGC');
  const response = await mounted.window.fetch('/api/documents', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({photo: {src: '/SGC/api/media/' + 'b'.repeat(64)}}),
  });
  assert.equal(mounted.calls[0].url, '/SGC/api/documents');
  assert.equal(JSON.parse(mounted.calls[0].options.body).photo.src, '/api/media/' + 'b'.repeat(64));
  assert.equal((await response.json()).photo.src, '/SGC/api/media/' + 'a'.repeat(64));
  assert.equal(mounted.window.sqaUrl('/SGC/api/documents'), '/SGC/api/documents');
  assert.equal(mounted.window.sqaUrl('/images/jardim.jpg'), '/SGC/images/jardim.jpg');
  assert.ok(!mounted.calls[0].url.includes('/SGC/SGC'));

  const plain = harness('');
  await plain.window.fetch('/api/documents');
  assert.equal(plain.calls[0].url, '/api/documents');
  assert.equal(plain.window.sqaUrl('/images/jardim.jpg'), '/images/jardim.jpg');
  console.log(JSON.stringify({status: 'APPROVED', assertions: 8}));
})().catch(error => { console.error(error); process.exit(1); });
