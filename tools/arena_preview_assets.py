#!/usr/bin/env python3
"""Render original prefab reference images using only the paused arena instance."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from arena_local import LocalClient,ROOT,FOLDER
from runtime import InstanceSession


def gallery(output,rows):
    visible=[r for r in rows if not r.get('error')and r.get('image')]
    width,height,columns=140,162,10
    sheet=Image.new('RGB',(width*columns,48+height*((len(visible)+columns-1)//columns)),(30,34,42))
    draw=ImageDraw.Draw(sheet);font=ImageFont.load_default(size=12)
    draw.text((10,8),'Original prefab poses. Red: enabled component bounds; yellow: disabled. Damage activation unverified.',font=font)
    for i,row in enumerate(visible):
        image=Image.open(output/row['image']).convert('RGB');pen=ImageDraw.Draw(image)
        for collider in row.get('colliders',[]):
            box=collider['box']
            if box[2]>box[0]and box[3]>box[1]:
                pen.rectangle(box,outline=(255,80,80)if collider['configured_enabled']else(240,210,70),width=2)
        image=image.resize((128,128));x=(i%columns)*width+6;y=48+(i//columns)*height
        sheet.paste(image,(x,y));draw.text((x,y+129),f'{row["kind"]}:{row["type_id"]}',font=font)
        draw.text((x,y+143),row['resource'][:20],font=font)
    sheet.save(output/'gallery.jpg',quality=92)


def render(entities,output,limit=None):
    output.mkdir(parents=True,exist_ok=False)
    rows=json.loads(entities.read_text());session=InstanceSession('arena');client=LocalClient(session)
    entries=[r for r in rows if r['gale_usage']['placements']and r.get('resource_name')]
    if limit is not None:
        entries=entries[:limit]
    source=(ROOT/'arena/Local/asset_preview.lua').read_text()
    (output/'sources.json').write_text(json.dumps(dict(lua_sha256=hashlib.sha256(source.encode()).hexdigest(),
        entities_sha256=hashlib.sha256(entities.read_bytes()).hexdigest()),indent=2)+'\n')
    results=[]
    with session.control():
        before=client.execute('return MR3A.state()',lease_held=True)
        before_enemies=client.execute('return CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.EnemyBase)).Length',lease_held=True)
        if before['timeScale']!=0:
            raise RuntimeError('Pause arena before generating reference images')
        try:
            client.execute('assert(load('+json.dumps(source)+'))();return true',lease_held=True)
            for entry in entries:
                name=entry['resource_name'];filename=f'{entry["kind"]}-{entry["type_id"]}.png'
                result=client.execute('return MR3A.preview_asset('+json.dumps(name)+','+json.dumps(filename)+')',lease_held=True)
                result.update(kind=entry['kind'],type_id=entry['type_id'])
                if not result.get('error'):
                    session.adb('pull',FOLDER+'/'+filename,str(output/filename)).check_returncode()
                    result['image']=filename
                    rgb=np.asarray(Image.open(output/filename).convert('RGB')).astype(np.int16)
                    corners=np.concatenate([rgb[:5,:5].reshape(-1,3),rgb[-5:,-5:].reshape(-1,3)])
                    background=np.median(corners,axis=0)
                    mask=np.max(abs(rgb-background),axis=2)>12
                    yy,xx=np.where(mask);result['foreground_pixels']=int(mask.sum())
                    if len(xx)>20:
                        result['visual_box']=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
                    else:
                        result.update(status='empty_render',error='No usable rendered foreground')
                results.append(result);print(json.dumps(result),flush=True)
                (output/'references.json').write_text(json.dumps(results,indent=2)+'\n')
        finally:
            after=client.execute('MR3A.menu_suppressed=false;MR3A.enable_menu();return MR3A.state()',lease_held=True)
            after_enemies=client.execute('return CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.EnemyBase)).Length',lease_held=True)
            valid=all(after[k]==before[k]for k in ('health','episodeFrame','mode','timeScale'))
            valid=valid and before_enemies==after_enemies and before['position']==after['position']
            (output/'state-check.json').write_text(json.dumps(dict(before=before,after=after,unchanged=valid,
                enemies_before=before_enemies,enemies_after=after_enemies),indent=2)+'\n')
            if not valid:
                raise RuntimeError('Preview changed original battle state')
    registry=entities.parent/'detector-classes.json'
    if registry.exists():
        classes=json.loads(registry.read_text())
        by_id={f'{r["kind"]}:{r["type_id"]}':r for r in results}
        for row in classes:
            ref=by_id.get(row['key'])
            if ref and not ref.get('error'):
                row['reference_examples']=[dict(image=str((output/ref['image']).resolve()),
                    box=ref.get('appearance_box',ref['visual_box']),pose='original_prefab_default',runtime_detection_verified=False)]
                row['collision_reference']=dict(image_size=[256,256],colliders=ref.get('colliders',[]),
                                               scope='default_pose_not_damage_activation',runtime_verified=False)
                row['status']='visual_reference_available_unvalidated'
            elif ref:
                row['reference_error']=ref.get('error')
                row['status']='requires_runtime_state'if row['renderable']else'logical_or_no_render'
        (output/'detector-classes-with-references.json').write_text(json.dumps(classes,indent=2)+'\n')
    gallery(output,results)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--entities',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--limit',type=int)
    a=p.parse_args();render(a.entities,a.output,a.limit)


if __name__=='__main__':
    main()
