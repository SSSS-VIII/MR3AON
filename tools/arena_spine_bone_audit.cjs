#!/usr/bin/env node
'use strict';
// Compare original isolated animation data at native TrackEntry.trackTime.
// Mixed/sliced/reversed tracks remain explicitly outside this audit.
const fs = require('fs');
const crypto = require('crypto');
const {argumentsFor, loadOriginal, applyIsolated} = require('./arena_spine_bone_profile.cjs');
const rows = value => Array.isArray(value) ? value : Object.values(value || {});
const stats = numbers => {
  const a = numbers.slice().sort((a, b) => a - b);
  return a.length ? {count: a.length, p50: a[Math.floor(a.length * .5)],
    p95: a[Math.floor(a.length * .95)], maximum: a[a.length - 1]} : {count: 0};
};

function audit(context, observations, args) {
  const pairs = [], skipped = {};
  const skip = reason => { skipped[reason] = (skipped[reason] || 0) + 1; };
  for (let frame = 0; frame < observations.length; frame++) {
    for (const enemy of rows(observations[frame].enemies)) {
      const s = enemy.spine;
      if (!s || !s.initialized) continue;
      if (s.asset_name !== args.assetName) { skip('other_asset'); continue; }
      if (s.tracks_truncated || s.bones_truncated) { skip('truncated'); continue; }
      const tracks = rows(s.tracks).filter(t => t.entry);
      if (tracks.length !== 1 || tracks[0].index !== 0) { skip('multiple_or_no_tracks'); continue; }
      const t = tracks[0].entry, anim = context.data.findAnimation(t.animation);
      if (t.mixing_from || t.reverse || t.alpha !== 1 || t.animationStart !== 0 ||
          !anim || Math.abs(t.animationEnd - anim.duration) > 1e-5) {
        skip('mixed_reversed_sliced_or_missing_animation'); continue;
      }
      const actual = new Map(rows(s.bones).map(b => [b.name, b]));
      if (args.bones.some(name => !actual.has(name))) { skip('missing_bone'); continue; }
      applyIsolated(context, t.animation, t.trackTime, t.loop, s.fields);
      for (const name of args.bones) {
        const predicted = context.skeleton.findBone(name), native = actual.get(name);
        pairs.push({frame, enemy_id: enemy.id, animation: t.animation, track_time: t.trackTime, bone: name,
          health: observations[frame].state.health,
          position_error_m_in_skeleton: Math.hypot(predicted.worldX - native.x, predicted.worldY - native.y),
          matrix_max_error: Math.max(...['a', 'b', 'c', 'd'].map(k => Math.abs(predicted[k] - native[k])))});
      }
    }
  }
  return {schema: 1, scope: 'Native isolated bone-pose audit; not collision, future state or route acceptance',
    asset_name: args.assetName, runtime_version: context.pkg.version, skeleton_version: context.data.version,
    skeleton_sha256: crypto.createHash('sha256').update(context.bytes).digest('hex'),
    pairs, skipped, position_error: stats(pairs.map(p => p.position_error_m_in_skeleton)),
    matrix_error: stats(pairs.map(p => p.matrix_max_error))};
}

if (require.main === module) {
  try {
    const argv = process.argv.slice(2), special = {};
    const rest = [];
    for (let i = 0; i < argv.length; i += 2) {
      if (argv[i] === '--observations' || argv[i] === '--asset-name') {
        if (!argv[i + 1] || argv[i] in special) throw new Error('Missing or repeated audit argument');
        special[argv[i]] = argv[i + 1];
      } else rest.push(argv[i], argv[i + 1]);
    }
    if (!special['--observations'] || !special['--asset-name'])
      throw new Error('Supply --observations and --asset-name');
    const args = argumentsFor(rest); args.assetName = special['--asset-name'];
    if (fs.existsSync(args.output)) throw new Error('Keep previous evidence: output already exists');
    const bytes = fs.readFileSync(special['--observations']);
    const observations = bytes.toString('utf8').trim().split('\n').map(JSON.parse);
    const result = audit(loadOriginal(args), observations, args);
    result.observations_sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
    result.source_sha256 = Object.fromEntries(['arena_spine_bone_profile.cjs', 'arena_spine_bone_audit.cjs']
      .map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(require('path').join(__dirname, name))).digest('hex')]));
    fs.writeFileSync(args.output, JSON.stringify(result, null, 2) + '\n', {flag: 'wx'});
    process.stdout.write(JSON.stringify({output: args.output, position_error: result.position_error,
      matrix_error: result.matrix_error, skipped: result.skipped}) + '\n');
  } catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
module.exports = {audit};
