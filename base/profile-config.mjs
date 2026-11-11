// @ts-check
/** Declarative image profiles: no network, installers, credentials or shell evaluation. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** @typedef {Record<string, unknown>} JsonObject */
const here = path.dirname(fileURLToPath(import.meta.url));
const resourceKeys = ['extensions', 'skills', 'prompts', 'themes'];
const profileName = /^[a-z][a-z0-9-]*$/;

/** @param {unknown} value @returns {JsonObject} */
function object(value) {
  assert.ok(value !== null && typeof value === 'object' && !Array.isArray(value), 'Expected a JSON object');
  return /** @type {JsonObject} */ (value);
}
/** @param {string} filename @returns {JsonObject} */
function readJson(filename) {
  try { return object(JSON.parse(readFileSync(filename, 'utf8'))); }
  catch (cause) { throw new Error(`Invalid JSON configuration: ${filename}`, { cause }); }
}
/** @param {unknown} value @returns {string[]} */
function strings(value) {
  assert.ok(Array.isArray(value) && value.every(item => typeof item === 'string' && item.trim()), 'Expected nonempty strings');
  return /** @type {string[]} */ (value);
}
/** @param {string} value */
function checkName(value) { assert.match(value, profileName, 'Invalid profile name'); }

/**
 * Resolve all profiles, rejecting cycles, unknown packages and ambiguous settings.
 * Package versions live only in package.json/package-lock.json; profiles select
 * from that installed catalog, not arbitrary npm/git sources to fetch at startup.
 * @param {string} directory
 * @param {JsonObject} manifest
 * @param {string} runtimeDirectory
 * @returns {Record<string, JsonObject>}
 */
export function compileProfiles(directory, manifest, runtimeDirectory) {
  assert.ok(path.isAbsolute(runtimeDirectory), 'Runtime package directory must be absolute');
  const dependencies = object(manifest.dependencies);
  const catalog = strings(object(manifest.piImage).extensions);
  assert.equal(new Set(catalog).size, catalog.length, 'Duplicate catalog package');
  for (const name of catalog) {
    assert.match(name, /^(?:@[a-z0-9-]+\/)?[a-z0-9][a-z0-9._-]*$/, 'Invalid package name');
    assert.equal(typeof dependencies[name], 'string', `Catalog package is not installed: ${name}`);
    assert.match(/** @type {string} */ (dependencies[name]), /^\d+\.\d+\.\d+(?:-[\w.-]+)?$/, 'Catalog versions must be exact');
  }
  /** @type {Record<string, JsonObject>} */
  const definitions = Object.create(null);
  for (const file of readdirSync(directory).filter(file => file.endsWith('.json')).sort()) {
    const name = file.slice(0, -5);
    checkName(name);
    definitions[name] = readJson(path.join(directory, file));
  }
  assert.ok(Object.keys(definitions).length, 'No profiles found');
  /** @type {Record<string, JsonObject>} */
  const compiled = Object.create(null);
  const visiting = new Set();
  /** @param {string} name @returns {JsonObject} */
  function resolve(name) {
    checkName(name);
    if (compiled[name]) return compiled[name];
    assert.ok(definitions[name], `Unknown profile: ${name}`);
    assert.ok(!visiting.has(name), `Profile inheritance cycle at ${name}`);
    visiting.add(name);
    const definition = definitions[name];
    assert.ok(Object.keys(definition).every(key => ['extends', 'packages', 'settings'].includes(key)), `Unknown profile field: ${name}`);
    /** @type {JsonObject} */
    let parent = {};
    if (definition.extends !== undefined) {
      assert.equal(typeof definition.extends, 'string', 'extends must name one profile');
      parent = resolve(/** @type {string} */ (definition.extends));
    }
    const settings = definition.settings === undefined ? {} : object(definition.settings);
    assert.ok(!['packages', ...resourceKeys].some(key => key in settings), 'Use profile packages/resource filters, not settings resource paths');
    if ('defaultTools' in settings) strings(settings.defaultTools);
    // Empty tool lists deliberately disable defaults and are valid.
    if ('defaultProjectTrust' in settings) assert.ok(['ask', 'never', 'always'].includes(String(settings.defaultProjectTrust)), 'Invalid project trust policy');
    if ('enableInstallTelemetry' in settings) assert.equal(typeof settings.enableInstallTelemetry, 'boolean', 'enableInstallTelemetry must be boolean');
    /** @type {unknown[]} */
    let packages;
    if (definition.packages === undefined) {
      packages = /** @type {unknown[]} */ (parent.packages ?? []);
    } else {
      const requested = definition.packages === 'all' ? catalog : definition.packages;
      assert.ok(Array.isArray(requested), 'packages must be all or an array');
      const seen = new Set();
      packages = requested.map(entry => {
        const selection = typeof entry === 'string' ? { name: entry } : object(entry);
        const packageName = selection.name;
        assert.ok(typeof packageName === 'string' && catalog.includes(packageName), `Unknown package: ${String(packageName)}`);
        assert.ok(!seen.has(packageName), `Duplicate selected package: ${packageName}`);
        seen.add(packageName);
        assert.ok(Object.keys(selection).every(key => ['name', ...resourceKeys].includes(key)), 'Unknown package selection field');
        /** @type {JsonObject} */
        const result = { source: path.join(runtimeDirectory, 'node_modules', packageName) };
        for (const key of resourceKeys) if (key in selection) result[key] = strings(selection[key]);
        return Object.keys(result).length === 1 ? result.source : result;
      });
    }
    const result = { ...parent, ...settings, packages };
    compiled[name] = result;
    visiting.delete(name);
    return result;
  }
  for (const name of Object.keys(definitions)) resolve(name);
  return compiled;
}

/** @param {string} data */
const digest = data => createHash('sha256').update(data).digest('hex');
/** @param {string} filename @param {string} content */
function atomicWrite(filename, content) {
  const temporary = `${filename}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, content, { flag: 'wx', mode: 0o600 });
    renameSync(temporary, filename);
  } finally {
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}

/**
 * Refresh only settings proven unchanged since our last seed. Existing operator
 * settings (including old unmarked seeds) always win; never silently adopt them.
 * A per-worker writable state directory must not be shared by running agents.
 * @param {string} defaultsDirectory
 * @param {string} stateDirectory
 * @param {string} profile
 * @returns {string}
 */
export function initializeProfile(defaultsDirectory, stateDirectory, profile) {
  checkName(profile);
  const seed = readFileSync(path.join(defaultsDirectory, profile, 'settings.json'), 'utf8');
  readJson(path.join(defaultsDirectory, profile, 'settings.json'));
  mkdirSync(stateDirectory, { recursive: true });
  const settingsFile = path.join(stateDirectory, 'settings.json');
  const markerFile = path.join(stateDirectory, '.image-profile.json');
  if (existsSync(settingsFile)) {
    let marker;
    try { marker = readJson(markerFile); } catch { return 'operator-owned'; }
    if (marker.settingsSha256 !== digest(readFileSync(settingsFile, 'utf8'))) return 'operator-owned';
    if (marker.profile === profile && marker.settingsSha256 === digest(seed)) return 'image-managed';
  }
  atomicWrite(settingsFile, seed);
  atomicWrite(markerFile, JSON.stringify({ profile, settingsSha256: digest(seed) }) + '\n');
  return 'image-managed';
}

/** @param {string[]} args */
function main(args) {
  if (args[0] === 'compile' && args.length === 2) {
    const profiles = compileProfiles(path.join(here, 'profiles'), readJson(path.join(here, 'package.json')), here);
    for (const [name, settings] of Object.entries(profiles)) {
      const directory = path.join(args[1], name);
      mkdirSync(directory, { recursive: true });
      writeFileSync(path.join(directory, 'settings.json'), JSON.stringify(settings, null, 2) + '\n');
    }
  } else if (args[0] === 'initialize' && args.length === 4) {
    initializeProfile(args[1], args[2], args[3]);
  } else {
    throw new Error('Usage: profile-config.mjs compile OUTPUT | initialize DEFAULTS STATE PROFILE');
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
