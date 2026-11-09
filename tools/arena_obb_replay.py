#!/usr/bin/env python3
"""Offline pixels/own-key state replay; native truth is scored afterwards only."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from arena_obb_detector import ObbDetector,ObbPerception,profile_path
from arena_vision import serializable
from arena_yolo_obb_data import collider_quad

SOURCE=Path(__file__).read_bytes()


def observe_own_input(actor,pixels,stamp,previous_stamp,previous_action):
    if previous_stamp is not None and previous_action not in(None,'none'):
        action=previous_action
        if action=='down'and actor.last_observation and actor.last_observation['phase']=='ground':
            action='slide'
        actor.action(action,previous_stamp)
    return actor.observe(pixels,stamp)


def state_family(phase):
    if phase.startswith('jump1'):return'jump1'
    if phase.startswith('jump2'):return'jump2'
    if phase.startswith('flip_'):return'transition'
    if phase.startswith('air_'):return'air'
    return phase


NATIVE_STATES={'runOnLine':'rope_above','runOnLineDown':'rope_below','runOnGround':'ground',
               'slideOnGround':'slide','jump':'jump1','fall':'air_or_jump1','jump2':'jump2','fall2':'jump2',
               'rollToLineDown':'transition','rollToLineOn':'transition','rollToGround':'transition'}


def replay(weights,episodes,output):
    output.mkdir(parents=True,exist_ok=False);cv2.setNumThreads(1)
    detector=ObbDetector(weights);counts=Counter();confusion=Counter();wall=[];errors=[]
    sources={}
    with(output/'observations.jsonl').open('w')as stream:
        for episode in episodes:
            labels=episode/'labels.jsonl';sources[str(episode)]=hashlib.sha256(labels.read_bytes()).hexdigest()
            actor=ObbPerception(detector);previous_stamp=None
            for line in labels.open():
                row=json.loads(line);pixels=cv2.cvtColor(cv2.imread(str(episode/row['image'])),cv2.COLOR_BGR2RGB)
                stamp=row['t'];begin=time.perf_counter()
                # These four values are the complete deployed actor input.
                obs=observe_own_input(actor,pixels,stamp,previous_stamp,row.get('previous_action'))
                wall.append((time.perf_counter()-begin)*1000);previous_stamp=stamp;counts['frames']+=1
                counts['unknown_player']+=obs['player']is None
                counts['predicted_player']+=bool(obs['player_predicted'])
                # Native physics/geometry enter only this diagnostic scoring.
                expected=NATIVE_STATES.get(row['physics'].split(':')[0]);actual=state_family(obs['phase'])
                if expected:
                    confusion[expected+' -> '+actual]+=1;counts['scored_states']+=1
                    counts['matched_states']+=(actual in('air','jump1')if expected=='air_or_jump1'else expected==actual)
                if obs['player']is not None and row['role']['colliders']:
                    q=collider_quad(row['role']['colliders'][0]);delta=q.mean(0)-obs['player'].center
                    errors.append(float(np.linalg.norm(delta)))
                stream.write(json.dumps(dict(episode=str(episode),image=row['image'],expected_state=expected,
                                             observation=serializable(obs)))+'\n')
    report=dict(counts,state_family_accuracy=counts['matched_states']/max(1,counts['scored_states']),
                confusion=dict(confusion),weights=str(weights),sha256=detector.sha256,sources=sources,
                profile_sha256=hashlib.sha256(profile_path(weights).read_bytes()).hexdigest(),
                replay_source_sha256=hashlib.sha256(SOURCE).hexdigest(),
                state_scope='Native fall does not distinguish walk-off from first-jump descent; either air/jump1 is accepted only for fall',
                role_center_error_px=dict(median=float(np.median(errors)),p95=float(np.percentile(errors,95)))if errors else None,
                pixel_to_state_ms=dict(median=float(np.median(wall)),p95=float(np.percentile(wall,95))),
                scope='Offline native recording with its own keys replayed; no gameplay control, capture latency or closed-loop success')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--weights',type=Path,required=True);p.add_argument('--episodes',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();replay(a.weights,a.episodes,a.output)
