"""Freeze model revisions and load them only between independent VM cases.

The active model imports from immutable private source files. Editing a source
in the workspace cannot change a half-completed branch or its evidence.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

MODEL_MODULES=('arena_privileged_geometry','arena_privileged_families',
    'arena_privileged_pinball','arena_privileged_model','arena_privileged_policy',
    'arena_privileged_runner','arena_privileged_catalog','privileged_search')


def digest_sources(root,names):
    return {name:hashlib.sha256((Path(root)/name).read_bytes()).hexdigest() for name in names}


def freeze(root,destination,names):
    root,destination=Path(root),Path(destination)
    data={name:(root/name).read_bytes() for name in names}
    hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in data.items()}
    revision=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    folder=destination/revision;folder.mkdir(parents=True,exist_ok=True)
    for name,raw in data.items():
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=raw:
            raise ValueError('Immutable model revision differs from its source manifest')
        path.write_bytes(raw)
    # A concurrent edit is deferred to the next independent case. Do not load
    # a revision assembled from different moments during an atomic patch set.
    if digest_sources(root,names)!=hashes:
        raise RuntimeError('Source changed during revision capture')
    (folder/'manifest.json').write_text(json.dumps(hashes,indent=2)+'\n')
    return revision,folder,hashes


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise ValueError('Cannot load frozen model source')
    module=importlib.util.module_from_spec(spec)
    previous=sys.modules.get(name)
    sys.modules[name]=module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if previous is None:sys.modules.pop(name,None)
        else:sys.modules[name]=previous
        raise
    return module


def activate(folder):
    folder=Path(folder)
    loaded={}
    for name in MODEL_MODULES:
        path=folder/(('arena_checkpoint_lab/' if name=='privileged_search' else '')+name+'.py')
        loaded[name]=load_module(name,path)
    return loaded['privileged_search'].run,loaded['arena_privileged_catalog'].build
