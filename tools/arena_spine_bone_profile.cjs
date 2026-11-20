#!/usr/bin/env node
/* Read original Spine 4.0 binary animation data without rendering or a client.
 * The official runtime is an external, locally installed dependency. Generated
 * bone samples are research evidence, not a collision envelope or route proof.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

function argumentsFor(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith('--') || i + 1 === argv.length)
      throw new Error('Expected --name value pairs');
    const name = argv[i].slice(2);
    if (!['runtime', 'input', 'output', 'skin', 'bones', 'scale', 'fps'].includes(name) || name in args)
      throw new Error('Unknown or repeated argument: ' + name);
    args[name] = argv[i + 1];
  }
  for (const name of ['runtime', 'input', 'output', 'scale', 'skin', 'bones'])
    if (!args[name]) throw new Error('Missing --' + name);
  args.scale = Number(args.scale); args.fps = Number(args.fps || 120);
  if (!(args.scale > 0 && Number.isFinite(args.scale)) || !(args.fps > 0 && args.fps <= 1000))
    throw new Error('Invalid scale or sampling rate');
  args.bones = [...new Set(args.bones.split(',').filter(Boolean))];
  if (!args.bones.length) throw new Error('Select at least one bone');
  return args;
}

function loadOriginal(args) {
  const runtime = path.resolve(args.runtime);
  const pkg = JSON.parse(fs.readFileSync(path.join(runtime, 'package.json'), 'utf8'));
  if (pkg.name !== '@esotericsoftware/spine-core' || !/^4\.0\./.test(pkg.version))
    throw new Error('Use the official Spine 4.0 core runtime for this source format');
  const source = fs.readFileSync(path.join(runtime, 'dist/iife/spine-core.js'), 'utf8');
  const spine = vm.runInNewContext(source + ';spine', {}, {timeout: 10000});
  const loader = {
    // Image UVs never enter bone/constraint evaluation. Deform timelines do
    // require their real mesh vertex data; do not omit mesh attachments.
    newRegionAttachment: () => null,
    newMeshAttachment: (skin, name) => {
      const mesh = new spine.MeshAttachment(name);
      mesh.region = {u: 0, v: 0, u2: 1, v2: 1};
      return mesh;
    },
    newBoundingBoxAttachment: (skin, name) => new spine.BoundingBoxAttachment(name),
    newPathAttachment: (skin, name) => new spine.PathAttachment(name),
    newPointAttachment: (skin, name) => new spine.PointAttachment(name),
    newClippingAttachment: (skin, name) => new spine.ClippingAttachment(name),
  };
  const bytes = fs.readFileSync(args.input);
  const reader = new spine.SkeletonBinary(loader); reader.scale = args.scale;
  const data = reader.readSkeletonData(new Uint8Array(bytes));
  if (!/^4\.0\./.test(data.version)) throw new Error('Skeleton/runtime version mismatch');
  const skeleton = new spine.Skeleton(data);
  skeleton.setSkinByName(args.skin);
  return {pkg, source, bytes, spine, data, skeleton};
}

function applyIsolated(context, name, time, loop = false, fields = {}) {
  const {spine, data, skeleton} = context;
  const animation = data.findAnimation(name);
  if (!animation) throw new Error('Original skeleton has no animation: ' + name);
  skeleton.setToSetupPose();
  skeleton.scaleX = fields.scaleX ?? 1; skeleton.scaleY = fields.scaleY ?? 1;
  skeleton.x = fields.x ?? 0; skeleton.y = fields.y ?? 0;
  animation.apply(skeleton, 0, time, loop, [], 1, spine.MixBlend.replace, spine.MixDirection.mixIn);
  skeleton.updateWorldTransform();
}

function profile(args) {
  const context = loadOriginal(args);
  const {pkg, source, bytes, data, skeleton} = context;
  const selected = args.bones.map(name => {
    const bone = skeleton.findBone(name);
    if (!bone) throw new Error('Original skeleton has no bone: ' + name);
    return bone;
  });
  const animations = [];
  for (const animation of data.animations) {
    const samples = [];
    for (let i = 0; i <= Math.ceil(animation.duration * args.fps); i++) {
      const t = Math.min(i / args.fps, animation.duration);
      applyIsolated(context, animation.name, t);
      samples.push({t, bones: selected.map(bone => ({name: bone.data.name,
        x: bone.worldX, y: bone.worldY, a: bone.a, b: bone.b, c: bone.c, d: bone.d}))});
    }
    animations.push({name: animation.name, duration: animation.duration, samples});
  }
  const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
  return {schema: 1, scope: 'Isolated animation samples; no track mixing, native timing or continuous collision guarantee',
    input: args.input, input_sha256: sha256(bytes), skeleton_version: data.version,
    runtime_version: pkg.version, runtime_sha256: sha256(source), scale: args.scale,
    skin: args.skin, fps: args.fps, bone_count: data.bones.length, selected_bones: args.bones, animations};
}

if (require.main === module) {
  try {
    const args = argumentsFor(process.argv.slice(2));
    if (fs.existsSync(args.output)) throw new Error('Keep prior evidence: output already exists');
    const result = profile(args);
    fs.mkdirSync(path.dirname(args.output), {recursive: true});
    fs.writeFileSync(args.output, JSON.stringify(result, null, 2) + '\n', {flag: 'wx'});
    process.stdout.write(JSON.stringify({output: args.output, skeleton_version: result.skeleton_version,
      bone_count: result.bone_count, animations: result.animations.length}) + '\n');
  } catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
module.exports = {argumentsFor, loadOriginal, applyIsolated, profile};
