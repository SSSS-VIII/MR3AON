#!/usr/bin/env python3
"""Legacy six/eight-class sphere trajectory audit; labels never drive inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
from arena_yolo_detector import YoloDetector,YoloPerception,ROOT
from arena_obb_detector import profile_path
from arena_vision_dataset import audit

LEGACY_WEIGHTS=ROOT/'debug/arena-client/yolo/finetune/fit-claw-v4/weights/best.pt'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--weights',type=Path,default=LEGACY_WEIGHTS)
    p.add_argument('--episode',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    metadata=profile_path(a.weights)
    if metadata.is_file()and json.loads(metadata.read_text()).get('task')=='obb':
        p.error('This audit uses legacy semantic classes; use arena_obb_replay.py for OBB state replay and arena_yolo_obb_score.py for native geometry')
    if a.output.exists():raise FileExistsError(a.output)
    cv2.setNumThreads(1)
    result=audit(a.episode,perception=YoloPerception(YoloDetector(a.weights)))
    result.update(weights=str(a.weights),sha256=hashlib.sha256(a.weights.read_bytes()).hexdigest(),
                  scope='Gameplay-plane spheres; same semantic class; visible ROI; stable camera forecasts only')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
