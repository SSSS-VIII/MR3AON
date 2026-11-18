"""Capture labelled references in speculative VM branches, then undo capture."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def install_lua(gate, source):
    gate.call('exec', code='MR3A.referenceChunks={};return true')
    for offset in range(0, len(source), 350):
        gate.call('exec', code='table.insert(MR3A.referenceChunks,' + json.dumps(source[offset:offset+350], ensure_ascii=False) + ');return true')
    return gate.call('exec', code="local s=table.concat(MR3A.referenceChunks);assert(#s>0,'Empty reference source');"
                     "assert(load(s,'@route-reference'))();MR3A.referenceChunks=nil;return true")


def install_observer(gate):
    # Read-only existing source; no update hook or restoration through fields.
    source = (ROOT / 'arena/Local/vision_labels.lua').read_text()
    install_lua(gate, source)
    gate.call('exec', code="assert(type(MR3A.vision_labels)=='function' and type(MR3A.vision_resolved_layout)=='function');return true")
    return hashlib.sha256(source.encode()).hexdigest()


class References:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=False)
        self.rows = []
        self.errors = []
        self.start = None
        self.sequence = 0
        self.abandoned = []

    def capture(self, gate, point, context):
        from search import BOARD
        gate.restore(point)
        before = gate.call('state')
        try:
            picture = gate.screenshot()
            current = gate.call('state')
            if current['episodeFrame'] != before['episodeFrame']:
                raise RuntimeError('A paused reference capture advanced native physics')
            board = gate.call('exec', code=BOARD)
            if (board['map'], board['stage_index']) != (context['map'], context['stage_index']):
                return
            layout = gate.call('exec', code='return MR3A.vision_resolved_layout()')
            name = f'{self.sequence:05d}.png'
            self.sequence += 1
            (self.folder / name).write_bytes(picture)
            row = dict(image=name, sha256=hashlib.sha256(picture).hexdigest(),
                       tick=current['episodeFrame'], state=current, board=board, context=context,
                       local_x=current['position']['x'] - board['stage_start'],
                       layout=layout, annotation_source='Native labels for a stored image only; never live actor input')
            self.rows.append(row)
            (self.folder / 'references.json').write_text(json.dumps(self.rows, ensure_ascii=False, indent=2))
        finally:
            gate.restore(point)

    def begin(self, gate, point, start):
        self.start = start
        self.capture(gate, point, start['board'])

    def window(self, gate, path, index):
        selected = path[-1]['point']
        try:
            # ~300ms normally, denser at input transitions. All captures are
            # undone before committing the already verified physical branch.
            points = [row for row in path if row['action'] != 'none']
            if index % 2 == 0:
                points.append(path[-1])
            seen = set()
            for row in points:
                if row['point'] in seen:
                    continue
                seen.add(row['point'])
                try:
                    self.capture(gate, row['point'], self.start['board'])
                except Exception as error:
                    self.errors.append(dict(tick=row['job']['after']['episodeFrame'], error=repr(error)))
        finally:
            gate.restore(selected)

    def status(self):
        return dict(count=len(self.rows), errors=self.errors, folder=str(self.folder),
                    physics_branch_preserved=True)

    def rewind(self, count):
        """Keep rejected images as evidence, but never publish them as the route."""
        if not 0 <= count <= len(self.rows):
            raise ValueError('Invalid reference rollback boundary')
        self.abandoned.extend(self.rows[count:])
        del self.rows[count:]
        (self.folder / 'abandoned-references.json').write_text(json.dumps(self.abandoned,ensure_ascii=False,indent=2))
        (self.folder / 'references.json').write_text(json.dumps(self.rows,ensure_ascii=False,indent=2))
