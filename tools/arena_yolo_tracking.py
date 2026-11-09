#!/usr/bin/env python3
"""Offline native-paired trajectory audit; privileged labels never drive inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
from arena_yolo_detector import YoloDetector,YoloPerception,DEFAULT_WEIGHTS
from arena_vision_dataset import audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--weights',type=Path,default=DEFAULT_WEIGHTS)
    p.add_argument('--episode',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    cv2.setNumThreads(1)
    result=audit(a.episode,perception=YoloPerception(YoloDetector(a.weights)))
    result.update(weights=str(a.weights),sha256=hashlib.sha256(a.weights.read_bytes()).hexdigest(),
                  scope='Gameplay-plane spheres; same semantic class; visible ROI; stable camera forecasts only')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
