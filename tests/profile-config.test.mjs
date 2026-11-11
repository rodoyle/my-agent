import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { compileProfiles, initializeProfile } from '../base/profile-config.mjs';

const root = path.resolve(import.meta.dirname, '..');
const manifest = JSON.parse(readFileSync(path.join(root, 'base/runtime/package.json'), 'utf8'));
const runtime = '/opt/pi-runtime';

test('shipped profiles inherit the catalog and apply per-agent settings', () => {
  const profiles = compileProfiles(path.join(root, 'base/profiles'), manifest, runtime);
  const all = manifest.piImage.extensions.map(name => path.join(runtime, 'node_modules', name));
  assert.deepEqual(profiles.base.packages, all);
  assert.deepEqual(profiles.devpod.packages, all);
  assert.deepEqual(profiles.devpod.defaultTools, ['read', 'bash', 'edit', 'write', 'grep', 'find', 'ls']);
  assert.deepEqual(profiles.headless.packages, []);
  assert.equal(profiles.headless.defaultProjectTrust, 'never');
  assert.deepEqual(profiles.template.packages, all);
});

test('profiles support resource filters, empty filters and empty tools', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'agent-profile-'));
  try {
    writeFileSync(path.join(directory, 'base.json'), JSON.stringify({ packages: 'all' }));
    writeFileSync(path.join(directory, 'filtered.json'), JSON.stringify({
      extends: 'base', packages: [{ name: 'pi-a', extensions: [], skills: ['skills/review'] }], settings: { defaultTools: [] },
    }));
    const result = compileProfiles(directory, { piImage: { extensions: ['pi-a'] }, dependencies: { 'pi-a': '1.2.3' } }, '/runtime');
    assert.deepEqual(result.filtered.packages, [{ source: '/runtime/node_modules/pi-a', extensions: [], skills: ['skills/review'] }]);
    assert.deepEqual(result.filtered.defaultTools, []);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('invalid catalogs, cycles and unknown package selections are rejected', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'agent-profile-'));
  try {
    writeFileSync(path.join(directory, 'base.json'), JSON.stringify({ packages: ['missing'] }));
    assert.throws(() => compileProfiles(directory, { piImage: { extensions: ['pi-a'] }, dependencies: { 'pi-a': '^1.2.3' } }, '/runtime'), /exact/);
    assert.throws(() => compileProfiles(directory, { piImage: { extensions: ['pi-a'] }, dependencies: { 'pi-a': '1.2.3' } }, '/runtime'), /Unknown package/);
    writeFileSync(path.join(directory, 'base.json'), JSON.stringify({ extends: 'base' }));
    assert.throws(() => compileProfiles(directory, { piImage: { extensions: ['pi-a'] }, dependencies: { 'pi-a': '1.2.3' } }, '/runtime'), /cycle/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test('mounted state follows image profile changes only while still image-managed', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'agent-profile-state-'));
  try {
    const defaults = path.join(directory, 'defaults');
    const state = path.join(directory, 'state');
    mkdirSync(path.join(defaults, 'base'), { recursive: true });
    mkdirSync(path.join(defaults, 'headless'));
    writeFileSync(path.join(defaults, 'base/settings.json'), '{"packages":["base"]}\n');
    writeFileSync(path.join(defaults, 'headless/settings.json'), '{"packages":[]}\n');
    assert.equal(initializeProfile(defaults, state, 'base'), 'image-managed');
    assert.equal(initializeProfile(defaults, state, 'headless'), 'image-managed');
    assert.equal(readFileSync(path.join(state, 'settings.json'), 'utf8'), '{"packages":[]}\n');
    writeFileSync(path.join(state, 'settings.json'), '{"packages":["operator"]}\n');
    assert.equal(initializeProfile(defaults, state, 'base'), 'operator-owned');
    assert.equal(readFileSync(path.join(state, 'settings.json'), 'utf8'), '{"packages":["operator"]}\n');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
