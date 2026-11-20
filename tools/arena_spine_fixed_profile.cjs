#!/usr/bin/env node
/* Cache original isolated poses on the float32 native fixed-update lattice.
 * Needs the separately installed official Spine 4.0 runtime and original asset.
 */
'use strict';
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {argumentsFor,loadOriginal,applyIsolated}=require('./arena_spine_bone_profile.cjs');

function fixedProfile(args,clips,tick) {
  if (!(Number.isFinite(tick)&&tick>0&&tick<=.1)||!clips.length)
    throw new Error('Select original animations and a bounded fixed tick');
  const c=loadOriginal(args),nativeTick=Math.fround(tick);
  const bones=args.bones.map(name=>{
    const b=c.skeleton.findBone(name);if(!b)throw new Error('Missing original bone: '+name);return b;
  });
  // A native full-scale Follow hierarchy requires unsheared local transforms.
  for(const b of bones)if(b.data.transformMode!==0||b.data.shearX||b.data.shearY)
    throw new Error('Unsupported local bone transform: '+b.data.name);
  const animations={};
  for(const name of clips){
    const animation=c.data.findAnimation(name);if(!animation)throw new Error('Missing animation: '+name);
    if(animation.timelines.some(t=>args.bones.includes(c.data.bones[t.boneIndex]?.name)&&t.constructor.name.includes('Shear')))
      throw new Error('Animated shear requires another native Follow model');
    let t=0;const samples=[];
    while(true){
      applyIsolated(c,name,t,false);
      const b=bones[bones.length-1];
      const pose=b=>({name:b.data.name,x:b.worldX,y:b.worldY,a:b.a,b:b.b,c:b.c,d:b.d});
      samples.push({t,bone:pose(b),bones:bones.map(pose)});
      if(t>=animation.duration)break;
      t=Math.fround(t+nativeTick);
      if(samples.length>10000)throw new Error('Unbounded animation sample count');
    }
    const keyed_properties={};
    for(const b of bones)keyed_properties[b.data.name]=animation.timelines.filter(t=>c.data.bones[t.boneIndex]?.name===b.data.name).map(t=>t.constructor.name);
    animations[name]={duration:animation.duration,keyed_properties,samples};
  }
  const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
  return {schema:1,scope:'Official isolated native float32 fixed-tick bone poses; no track mixing, phase or collision guarantee',
    asset_name:path.basename(args.input),skeleton_sha256:sha(c.bytes),runtime_sha256:sha(c.source),runtime_version:c.pkg.version,
    skeleton_version:c.data.version,scale:args.scale,skin:args.skin,tick:nativeTick,
    skeleton_bones:bones.map(b=>({name:b.data.name,parent:b.data.parent?.name,transform_mode:b.data.transformMode,shear_x:b.data.shearX,shear_y:b.data.shearY})),animations};
}

if(require.main===module){
  try{
    const remaining=[],extra={};const argv=process.argv.slice(2);
    for(let i=0;i<argv.length;i+=2){
      if(['--clips','--tick','--asset-name'].includes(argv[i])){
        if(extra[argv[i]]!==undefined||argv[i+1]===undefined)throw new Error('Missing or repeated fixed profile argument');
        extra[argv[i]]=argv[i+1];
      }else remaining.push(argv[i],argv[i+1]);
    }
    const args=argumentsFor(remaining),clips=(extra['--clips']||'').split(',').filter(Boolean);
    const result=fixedProfile(args,clips,Number(extra['--tick']));
    if(extra['--asset-name'])result.asset_name=extra['--asset-name'];
    fs.mkdirSync(path.dirname(args.output),{recursive:true});
    fs.writeFileSync(args.output,JSON.stringify(result)+'\n',{flag:'wx'});
    process.stdout.write(JSON.stringify({output:args.output,animations:clips,tick:result.tick})+'\n');
  }catch(error){process.stderr.write(error.message+'\n');process.exitCode=1;}
}
module.exports={fixedProfile};
