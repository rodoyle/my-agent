// Credential-free image contract. Run as the final image user, never as root.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawn, execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire('/opt/pi-runtime/package.json');
const runtimeManifest = require('/opt/pi-runtime/package.json');
const agentDirectory = process.env.PI_CODING_AGENT_DIR ?? path.join(process.env.HOME ?? '/home/agent', '.pi/agent');
const settings = JSON.parse(readFileSync(path.join(agentDirectory, 'settings.json'), 'utf8'));
assert.ok(Array.isArray(settings.packages), 'profile settings must contain a packages array');
const selectedPackages = new Map(settings.packages.map(entry => {
  const source = typeof entry === 'string' ? entry : entry?.source;
  assert.equal(typeof source, 'string', 'profile package requires a source');
  assert.ok(path.isAbsolute(source), `profile source must be absolute: ${source}`);
  return [source, !(typeof entry === 'object' && Array.isArray(entry.extensions) && entry.extensions.length === 0)];
}));
assert.equal(process.getuid(), 1000, 'image must default to the non-root agent');
assert.equal(process.versions.bun, undefined, 'Pi verification must run on Node');
assert.ok(Number(process.versions.node.split('.')[0]) >= 22);
for (const [command, args] of [
  ['node', ['--version']], ['npm', ['--version']], ['bun', ['--version']],
  ['pi', ['--version']], ['herdr', ['--version']], ['git', ['--version']],
  ['gh', ['--version']], ['ast-grep', ['--version']],
]) {
  const output = execFileSync(command, args, { encoding: 'utf8', timeout: 15000 });
  assert.ok(output.trim(), `${command} did not report its version`);
  console.log(output.trim().split('\n')[0]);
}
const k8s = await import(pathToFileURL(require.resolve('@kubernetes/client-node')).href);
assert.equal(typeof k8s.KubeConfig, 'function'); // no kubeconfig access or API calls
const napi = require('@ast-grep/napi');
assert.equal(typeof napi.parse, 'function');
assert.equal(napi.parse('JavaScript', 'const answer = 42;').root().kind(), 'program');

// Get real registered resources, not just installed-package metadata. No prompts,
// providers, tokens, model requests, or permission bypasses are involved.
const child = spawn('pi', ['--mode', 'rpc', '--no-session', '--no-approve'], {
  env: { ...process.env, PI_OFFLINE: '1', PI_TELEMETRY: '0' },
  stdio: ['pipe', 'pipe', 'pipe'],
});
let stderr = '';
let pending = '';
const responses = new Map();
const deadline = setTimeout(() => {
  child.kill('SIGKILL');
}, 60000);
try {
  await new Promise((resolve, reject) => {
    child.on('error', reject);
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.stdout.on('data', chunk => {
      pending += chunk.toString('utf8');
      let lf;
      while ((lf = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, lf).replace(/\r$/, '');
        pending = pending.slice(lf + 1);
        if (!line) continue;
        try {
          const record = JSON.parse(line);
          if (record.type === 'response') {
            assert.equal(record.success, true, JSON.stringify(record));
            responses.set(record.id, record);
            if (responses.has('commands') && responses.has('state')) child.stdin.end();
          }
        } catch (error) { child.kill('SIGKILL'); reject(error); }
      }
    });
    child.on('exit', (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`Pi exited code=${code} signal=${signal}\n${stderr}`));
    });
    child.stdin.on('error', reject);
    child.stdin.write('{"id":"commands","type":"get_commands"}\n');
    child.stdin.write('{"id":"state","type":"get_state"}\n');
  });
  assert.ok(responses.has('state'), 'Pi RPC did not answer get_state');
  const commands = responses.get('commands')?.data.commands ?? [];
  for (const name of runtimeManifest.piImage.extensions) {
    const source = path.join('/opt/pi-runtime/node_modules', name);
    const shouldLoad = selectedPackages.get(source) === true;
    const loaded = commands.some(command => command.source === 'extension'
      && JSON.stringify(command.sourceInfo).includes(source));
    assert.equal(loaded, shouldLoad, `Profile ${process.env.AGENT_PROFILE} package ${name}: expected loaded=${shouldLoad}; stderr: ${stderr}`);
  }
  console.log(`PASS: non-root Node Pi RPC; ${selectedPackages.size} profile package(s), native AST and Kubernetes imports`);
} finally {
  clearTimeout(deadline);
  if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
}
