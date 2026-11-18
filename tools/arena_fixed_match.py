"""Pixels-only place recognition and monotone progress inside a board visit.

Only stored labelled images, current pixels and the existing visual observation
enter this module. Evaluation telemetry and native instance IDs are not inputs.
"""
from collections import deque
import hashlib
import inspect
import json
import math
from pathlib import Path
import cv2
import numpy as np

SIZE = (320, 180)
MAX_POINTS = 128
MAX_LANDMARKS = 48
KINDS = ('spider', 'eye_enemy', 'pinball', 'trap', 'projectile', 'bamboo', 'mace', 'other')


def static_box_anchor(detection, observation):
    """Coarse box detections need evidence before supplying static world X.

    Stored references use declared static X, offline only. Live pixels use
    repeated visual tracking relative to measured scene flow, never entity IDs.
    Vertical trap animation does not invalidate its fixed horizontal anchor.
    """
    if (detection.kind!='trap' or detection.collider_shape!='BoxCollider'
            or detection.confidence<.7):
        return False
    x,y=detection.box.center
    reference=observation.get('reference_static_box_x')
    if reference is not None:
        return any(abs(x-expected)<=10 for expected in reference)
    scene=observation.get('scene_velocity_x')
    if not observation.get('scene_motion_observed')or scene is None:
        return False
    for track in observation.get('tracks',[]):
        if (track.kind!='trap' or track.collider_shape!='BoxCollider' or track.observations<3
                or not 0<=observation['time']-track.seen<=.1):
            continue
        tx,ty=track.box.center
        if (abs(tx-x)<=5 and abs(ty-y)<=8 and abs(track.vx-scene)<=45):
            return True
    return False


def semantic(observation):
    out = np.zeros(len(KINDS) * 4, np.float32)
    for obj in observation.get('detections', []):
        if obj.confidence < .3:
            continue
        kind = obj.kind if obj.kind in KINDS else 'other'
        cell = min(3, max(0, int(obj.box.center[0] / 160)))
        out[KINDS.index(kind) * 4 + cell] += 1
    return out


def features(image, observation=None):
    rgb = cv2.resize(image[:, :, :3], SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = np.zeros(gray.shape, np.uint8)
    mask[32:145, 128:315] = 255
    if observation:
        for d in observation.get('detections', []):
            x, y, w, h = d.box.x / 2, d.box.y / 2, d.box.w / 2, d.box.h / 2
            cv2.rectangle(mask, (max(0, int(x)-3), max(0, int(y)-3)),
                          (min(319, int(x+w)+3), min(179, int(y+h)+3)), 0, -1)
    orb = cv2.ORB_create(nfeatures=MAX_POINTS, edgeThreshold=8, patchSize=21, fastThreshold=9)
    keys, desc = orb.detectAndCompute(gray, mask)
    xy = np.zeros((MAX_POINTS, 2), np.float32)
    descriptors = np.zeros((MAX_POINTS, 32), np.uint8)
    count = 0 if desc is None else min(MAX_POINTS, len(desc))
    if count:
        xy[:count] = [k.pt for k in keys[:count]]
        descriptors[:count] = desc[:count]
    patch = cv2.resize(gray[32:145, 128:315], (32, 32)).astype(np.float32)
    low = cv2.dct(patch)[:8, :8].flatten()
    low[0] = 0
    low /= max(1., float(np.linalg.norm(low)))
    observation = observation or {}
    player = observation.get('player')
    root = observation.get('root_screen_x')
    if root is None and player is not None:
        root = player.center[0] - .052*observation.get('scale_px', 39.5)
    landmarks = []
    if root is not None:
        for d in observation.get('detections', []):
            name = (d.resource or '').lower()
            group = (1 if d.kind == 'spider' and 'muppet' not in name else
                     2 if 'hideblade' in name or static_box_anchor(d,observation) else None)
            if group and d.confidence >= .4:
                landmarks.append((group, d.box.center[0]-root, d.box.center[1]))
        for s in observation.get('visible_supports', []):
            if s['kind'] not in ('rope', 'platform') or s['confidence'] < .6:
                continue
            for side, clipped in (('a', 'left_clipped'), ('b', 'right_clipped')):
                x, y = s[side]
                if not s.get(clipped) and 15 < x < 625:
                    landmarks.append((3 if s['kind']=='platform' else 4, x-root, y))
    array = np.zeros((MAX_LANDMARKS, 3), np.float32)
    n = min(MAX_LANDMARKS, len(landmarks))
    if n:
        array[:n] = landmarks[:n]
    return dict(coarse=low, points=xy, descriptors=descriptors, count=count,
                semantic=semantic(observation), landmarks=array, landmark_count=n)


def feature_signature():
    code=inspect.getsource(features)+inspect.getsource(semantic)+inspect.getsource(static_box_anchor)
    return hashlib.sha256(code.encode()).hexdigest()


def landmark_shifts(reference, current):
    """Match fixed gameplay-plane X anchors; keep repeated translations apart.

    Background parallax is deliberately excluded. Moving balls, flying enemies,
    warnings, projectiles and floating platforms cannot supply world progress.
    """
    a = reference['landmarks'][:reference['landmark_count']]
    b = current['landmarks'][:current['landmark_count']]
    if min(len(a), len(b)) < 2:
        return []
    pairs = [(i, j, float(q[1]-p[1])) for i, p in enumerate(a) for j, q in enumerate(b) if p[0]==q[0]]
    bins = {}
    for _, _, shift in pairs:
        bins[round(shift/4)] = bins.get(round(shift/4), 0)+1
    result = []
    for bucket in sorted(bins, key=bins.get, reverse=True)[:12]:
        candidate = bucket*4
        nearby = sorted((p for p in pairs if abs(p[2]-candidate)<6), key=lambda p: abs(p[2]-candidate))
        used_a, used_b, selected = set(), set(), []
        for i, j, shift in nearby:
            if i not in used_a and j not in used_b:
                used_a.add(i);used_b.add(j);selected.append((i,j,shift))
        if len(selected)<2 or np.ptp([a[i,1] for i,_,_ in selected])<25:
            continue
        shift = float(np.median([s for _,_,s in selected]))
        error = float(np.median([abs(s-shift)for _,_,s in selected]))
        if error>4 or any(abs(shift-r['dx'])<10 for r in result):
            continue
        result.append(dict(dx=shift, std=(error+1.5)/39.5,
                           agreement=len(selected)/max(2,min(len(a),len(b))), count=len(selected)))
    return result


def register(reference, current):
    if min(reference['count'], current['count']) < 8:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(reference['descriptors'][:reference['count']],
                             current['descriptors'][:current['count']], k=2)
    good = [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < .76*b.distance]
    if len(good) < 8:
        return None
    source = np.array([reference['points'][m.queryIdx] for m in good], np.float32)
    target = np.array([current['points'][m.trainIdx] for m in good], np.float32)
    matrix, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
        ransacReprojThreshold=2., maxIters=500, confidence=.98)
    if matrix is None:
        return None
    scale = math.hypot(matrix[0, 0], matrix[1, 0])
    angle = abs(math.atan2(matrix[1, 0], matrix[0, 0]))
    selected = inliers.ravel().astype(bool)
    n = int(selected.sum())
    if n < 8 or not .96 <= scale <= 1.04 or angle > .04:
        return None
    residual = np.linalg.norm(source @ matrix[:, :2].T + matrix[:, 2] - target, axis=1)[selected]
    return dict(dx=float(matrix[0, 2]), dy=float(matrix[1, 2]), inliers=n,
                ratio=n/len(good), residual=float(np.median(residual)))


def identity(row):
    return tuple(row[k] for k in ('level', 'map', 'slot', 'stage'))


class Atlas:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.meta = json.loads((self.folder / 'index.json').read_text())
        if self.meta.get('schema') != 1 or self.meta.get('mode') != 6:
            raise ValueError('Unknown Gale visual atlas schema')
        self.rows = self.meta['references']
        # NpzFile is lazy: indexing it inside every candidate would repeatedly
        # inflate the whole descriptor array and stall a live input frame.
        with np.load(self.folder / 'features.npz', allow_pickle=False) as archive:
            self.data = {name: archive[name] for name in archive.files}
        self.coarse = self.data['coarse']
        self.contexts = {c['key']: c for c in self.meta['contexts']}
        self.layout_features={key:dict(landmarks=np.asarray([[kind,x*39.5,0]for kind,x in c['anchors']],np.float32),
                                      landmark_count=len(c['anchors']))
                              for key,c in self.contexts.items()if c.get('fixed')and len(c.get('anchors',[]))>=3}
        # OpenCV/BLAS lazy initialization belongs before gameplay resumes.
        warm = features(np.random.default_rng(0).integers(0,256,(180,320,3),dtype=np.uint8))
        register(warm, warm)
        if len(self.rows):
            self.coarse @ warm['coarse']

    def feature(self, index):
        return dict(points=self.data['points'][index], descriptors=self.data['descriptors'][index],
                    count=int(self.data['count'][index]), semantic=self.data['semantic'][index],
                    landmarks=self.data['landmarks'][index], landmark_count=int(self.data['landmark_count'][index]))

    def match(self, image, observation, prior=None):
        query = features(image, observation)
        self.last_query = query
        if query['count'] < 8 and query['landmark_count'] < 2 or not len(self.rows):
            return []
        indices = np.arange(len(self.rows))
        if prior:
            allowed = []
            for i, row in enumerate(self.rows):
                current = identity(row) == prior['identity']
                following = row['level'] == prior['identity'][0] and row['map'] == prior['identity'][1] and row['slot'] == prior['identity'][2] + 1
                near_exit = prior.get('near_exit',False) or prior.get('progress') is not None and prior['progress'] >= prior['length'] - 18
                loop_pool = (row['level'],row['map'],row['slot']) == prior['identity'][:3]
                loop_entry = (loop_pool and prior.get('loop') and prior.get('progress') is not None
                              and prior['progress'] >= prior['length'] and row['local_x']<8)
                if (current and (prior.get('progress') is None or abs(row['local_x']-prior['progress']) < 24)
                        or following and near_exit or loop_entry):
                    allowed.append(i)
            # A blank or occluded frame does not permit skipping several
            # boards in a map whose background is shared by every slot.
            indices = np.asarray(allowed, dtype=int)
            if not len(indices):
                return []
        coarse = self.coarse[indices] @ query['coarse']
        selected = indices[np.argsort(coarse)[-min(24, len(indices)):][::-1]]
        candidates = []
        background_scores={}
        for i in selected:
            row = self.rows[int(i)]
            stored = self.feature(int(i))
            match = register(stored, query)
            shifts = landmark_shifts(stored, query)
            if match is None and not shifts:
                continue
            if match is None and (not prior or identity(row)!=prior['identity']):
                continue
            a = self.data['semantic'][i]
            b = query['semantic']
            # A newly visible moving hazard cannot invalidate independently
            # aligned static geometry. Keep the hard presence check for bare
            # background guesses; geometry candidates retain the score penalty.
            if (not shifts and np.any((b.reshape(len(KINDS),4).sum(1)>0) &
                                      (a.reshape(len(KINDS),4).sum(1)==0))):
                continue
            agreement = 1. - float(np.abs(a-b).sum()) / max(1., float((a+b).sum()))
            score = (min(1., match['inliers']/22)*match['ratio'] if match else .55) * (.5+.5*agreement)
            if match:
                place=(row['level'],row['map'])
                background_scores[place]=max(background_scores.get(place,0),score)
            scale = self.contexts[row['key']].get('background_scale')
            if shifts:
                for shifted in shifts:
                    candidates.append(dict(row=row, identity=identity(row),
                        score=score*(.65+.35*shifted['agreement'])*min(1.,shifted['count']/3),
                        progress=row['local_x']-shifted['dx']/39.5, std=shifted['std'],
                        registration=match, progress_source='static_foreground', landmark_count=shifted['count']))
            else:
                progress = row['local_x'] - match['dx']/scale if scale and match else None
                std = (match['residual']+.4)/scale+.03 if scale and match else float('inf')
                candidates.append(dict(row=row, identity=identity(row), score=score,
                                       progress=progress, std=std, registration=match,progress_source='background'))
        static=query['landmarks'][:query['landmark_count']]
        static=static[np.isin(static[:,0],(1,2))]
        if len(static)>=3:
            current=dict(landmarks=static,landmark_count=len(static))
            for key,source in self.layout_features.items():
                context=self.contexts[key]
                place=(context['level'],context['map'])
                background=background_scores.get(place,0)
                if prior:
                    own=identity(context)==prior['identity']
                    following=place==prior['identity'][:2]and context['slot']==prior['identity'][2]+1
                    near_exit=prior.get('near_exit',False)or(prior.get('progress')is not None
                                       and prior['progress']>=prior['length']-18)
                    if not own and not(following and near_exit):
                        continue
                if background<.25 and not(prior and place==prior['identity'][:2]):
                    continue
                for aligned in landmark_shifts(source,current):
                    progress=-aligned['dx']/39.5
                    if aligned['count']<3 or aligned['agreement']<.75 or not 0<=progress<=context['length']+1:
                        continue
                    candidates.append(dict(row=context,identity=identity(context),progress=progress,
                        std=aligned['std'],score=min(1.,.55+.12*aligned['count'])*aligned['agreement']*(.9+.1*background),
                        registration=None,progress_source='original_static_layout',landmark_count=aligned['count']))
        # A single periodic rope endpoint cannot establish an absolute place.
        # Once the board and progress are known, it can correct accumulated
        # motion error without confusing this boundary with one 32m earlier.
        if prior and prior.get('progress')is not None and prior.get('std',0)<=1:
            endpoints=query['landmarks'][:query['landmark_count']]
            endpoints=endpoints[endpoints[:,0]==4]
            for context in self.contexts.values():
                if identity(context)!=prior['identity']:continue
                for kind,x in context.get('support_anchors',[]):
                    for point in endpoints:
                        if point[0]!=kind:continue
                        progress=x-float(point[1])/39.5
                        if abs(progress-prior['progress'])>max(.8,3*prior.get('std',0)):
                            continue
                        candidates.append(dict(row=context,identity=identity(context),progress=progress,
                            std=.12,score=.7,registration=None,progress_source='prior_and_original_support',
                            landmark_count=1))
        return sorted(candidates, key=lambda c: c['score'], reverse=True)


class BoardTracker:
    def __init__(self, atlas):
        self.atlas = atlas
        self.last = None
        self.visit = 0
        self.pending = None
        self.pending_count = 0
        self.state = dict(status='unknown', identity=None, localized=False)
        self.last_velocity = None
        self.positions = deque(maxlen=8)
        self.confirmed_identity = None
        self.registered_time = None
        self.cycle = 0
        self.odometer_base = 0.

    def recognition_prior(self, timestamp=None):
        # Shared empty entrance frames can suggest several different boards.
        # Only an actual spatial registration may constrain later candidates;
        # a background-only suggestion must never trap recognition in a wrong
        # board for the rest of the run.
        if self.confirmed_identity is None or self.last is None:
            return None
        # An expired position can still narrow a short board transition. The
        # context also expires so a boss/map change cannot stay locked forever.
        if timestamp is not None and self.registered_time is not None and timestamp-self.registered_time>8:
            return None
        level, world, slot, stage = self.confirmed_identity
        context = self.atlas.contexts[f'L{level}-M{world}-S{slot}-B{stage}']
        precise=(self.last['std']<=1 and (timestamp is None or timestamp-self.last['time']<=.18))
        return dict(identity=self.confirmed_identity,progress=self.last['progress']if precise else None,
                    std=self.last['std'],length=context['length'],loop=context.get('loop',False),
                    near_exit=self.last['progress']>=context['length']-18)

    def advance_odometry(self, observation):
        """Keep a visit through short occlusions using measured scene motion.

        Velocity comes from static gameplay-plane anchors in the existing
        visual layer. Background parallax and native speed are never used.
        Every uncertain interval accumulates error instead of resetting it.
        """
        if self.last is None:
            return
        dt = observation['time']-self.last['time']
        if not 0 <= dt <= .18:
            return
        velocity = self.last_velocity
        measured = False
        scale = observation.get('scale_px', 39.5)
        raw = observation.get('scene_velocity_x')
        if observation.get('scene_motion_observed') and raw is not None:
            proposed = (-raw+observation.get('vx', 0))/scale
            if 0 <= proposed <= 40 and (velocity is None or abs(proposed-velocity) <= 6):
                velocity = proposed
                measured = True
        if velocity is not None:
            self.last['progress'] += velocity*dt
            self.last['std'] += (.12 if measured else .7)*dt
            self.last['time'] = observation['time']
            self.last_velocity = velocity

    def coast(self, prediction, status):
        if prediction is None or prediction['std'] > .5:
            return None
        level, world, slot, stage = prediction['identity']
        key = f'L{level}-M{world}-S{slot}-B{stage}'
        context = self.atlas.contexts[key]
        progress = prediction['progress']
        block = next((b['index'] for b in context.get('blocks', [])
                      if b['start_x'] <= progress < b['finish_x']), None)
        return dict(status='tracked', identity=prediction['identity'], key=key, visit=self.visit,
                    progress_x=progress, progress_std=prediction['std'], block_instance=block,
                    loop_cycle=self.cycle, absolute_progress=self.odometer_base+progress,
                    localized=True, confidence=None, visual_match=status)

    def confirm(self, key,carry=None):
        if self.confirmed_identity == key:
            self.pending = key
            return True
        self.pending_count = self.pending_count + 1 if self.pending == key else 1
        self.pending = key
        if self.pending_count < 3:
            return False
        if self.confirmed_identity != key:
            self.visit += 1
            self.confirmed_identity = key
            self.last = None
            self.positions.clear()
            self.cycle = 0
            self.odometer_base = 0.
            if carry is not None:
                level,world,slot,stage=key
                context=self.atlas.contexts[f'L{level}-M{world}-S{slot}-B{stage}']
                self.last=dict(carry,identity=key,progress=carry['progress']-carry['length'],
                               length=context['length'],loop=context.get('loop',False),std=carry['std']+.03)
                self.positions.append((carry['time'],self.last['progress']))
        return True

    def predict(self, observation):
        if self.last is None:
            return None
        dt = observation['time'] - self.last['time']
        if not 0 <= dt <= .18:
            return None
        p = self.last.copy()
        if self.last_velocity is not None:
            p['progress'] += self.last_velocity * dt
            p['std'] += .12*dt
        else:
            p['std'] += 20*dt
        return p

    def observe(self, image, observation):
        self.advance_odometry(observation)
        prediction = self.predict(observation)
        prior=prediction if prediction and prediction['std']<=1 else self.recognition_prior(observation['time'])
        candidates = self.atlas.match(image, observation, prior)
        plausible = []
        for item in candidates:
            if item['progress'] is None or item['score'] < .42:
                continue
            loop_transition = (prediction and prediction.get('loop') and prediction['progress'] >= prediction['length']
                               and item['identity'][:3] == prediction['identity'][:3])
            if loop_transition and prediction['length'] <= item['progress'] <= prediction['length']+4:
                item['progress'] -= prediction['length']
            if prediction and item['identity'] == prediction['identity']:
                margin = max(.8, 3*(prediction['std']+item['std']))
                wraps = bool(loop_transition and 0 <= item['progress'] <= 4)
                if abs(item['progress'] - prediction['progress']) > margin and not wraps:
                    continue
                item['wraps'] = bool(wraps)
            elif loop_transition and 0 <= item['progress'] <= 4:
                item['wraps'] = True
            plausible.append(item)
        if any(c.get('wraps') for c in plausible):
            plausible = [c for c in plausible if c.get('wraps')]
        if not plausible:
            visible = [c for c in candidates if c['score'] >= .42]
            distinctive=bool(visible and not any(c['identity']!=visible[0]['identity']and
                visible[0]['score']-c['score']<.09 for c in visible[1:]))
            if distinctive and prediction and prediction['progress']>=prediction['length']:
                first=visible[0]
                following=(first['identity'][:2]==prediction['identity'][:2]
                           and first['identity'][2]==prediction['identity'][2]+1)
                level,world,slot,stage=prediction['identity']
                previous_context=self.atlas.contexts.get(f'L{level}-M{world}-S{slot}-B{stage}',{})
                if (following and prediction['std']<=.97 and previous_context.get('fixed') and observation.get('detections')
                        ):
                    confirmed=self.confirm(first['identity'],carry=prediction)
                    if confirmed:
                        carried=self.coast(self.last,'next_board_visual_identity')
                        self.state=carried or dict(status='identified',identity=first['identity'],
                            key=first['row']['key'],visit=self.visit,localized=False,
                            progress_x=self.last['progress'],progress_std=self.last['std'])
                    else:
                        self.state=self.coast(prediction,'confirming_next_board')or dict(
                            status='confirming',identity=first['identity'],key=first['row']['key'],localized=False)
                    return self.state
            coast = self.coast(prediction, 'missing')
            if coast is not None:
                self.state = coast
                return self.state
            if distinctive:
                first = visible[0]
                confirmed = self.confirm(first['identity'])
                if self.last is None:
                    self.state=dict(status='tentative',identity=None,suggested_identity=first['identity'],
                                    localized=False,confidence=first['score'])
                else:
                    self.state = dict(status='identified' if confirmed else 'confirming',
                                      identity=first['identity'], key=first['row']['key'],
                                      visit=self.visit, localized=False, confidence=first['score'])
            else:
                self.pending=None;self.pending_count=0
                self.state = dict(status='unknown', identity=None, localized=False)
            return self.state
        first = plausible[0]
        # Equal-looking repeated patterns are separate spatial hypotheses.
        competing = [c for c in plausible[1:] if c['identity'] != first['identity']
                     or abs(c['progress']-first['progress']) > max(1.2, 3*(c['std']+first['std']))]
        if competing and first['score'] - competing[0]['score'] < .09:
            coast = self.coast(prediction, 'ambiguous')
            if coast is not None:
                self.state = coast
                return self.state
            self.pending=None;self.pending_count=0
            self.state = dict(status='ambiguous', identity=None, localized=False)
            return self.state
        key = first['identity']
        old_cycle, old_odometer = self.cycle, self.odometer_base
        was_identity = self.confirmed_identity
        if not self.confirm(key):
            self.state = dict(status='confirming', identity=key, localized=False)
            return self.state
        context = self.atlas.contexts[first['row']['key']]
        progress = first['progress']
        if first.get('wraps'):
            if was_identity == key:self.visit += 1
            self.cycle=old_cycle+1;self.odometer_base=old_odometer+prediction['length']
            self.last=None;self.positions.clear()
        elif prediction and prediction['identity'] == key:
            # Absolute image registration can correct odometry drift. Retain
            # monotonicity against the last registered position, rather than
            # turning every optimistic prediction into an irreversible floor.
            progress = max(self.positions[-1][1] if self.positions else 0, progress)
        self.positions.append((observation['time'], progress))
        scale = observation.get('scale_px', 39.5)
        raw_v = observation.get('scene_velocity_x')
        if observation.get('scene_motion_observed') and raw_v is not None:
            self.last_velocity = -raw_v / scale + observation.get('vx', 0) / scale
        else:
            if len(self.positions) >= 3 and self.positions[-1][0]-self.positions[0][0] >= .08:
                times = np.array([t-self.positions[-1][0] for t, _ in self.positions])
                distances = np.array([x for _, x in self.positions])
                design = np.column_stack([np.ones(len(times)), times])
                fit, _, _, _ = np.linalg.lstsq(design, distances, rcond=None)
                if 0 <= fit[1] <= 40:
                    self.last_velocity = float(fit[1])
        blocks = context.get('blocks', [])
        block = next((b['index'] for b in blocks if b['start_x'] <= progress < b['finish_x']), None)
        self.last = dict(identity=key, progress=progress, std=first['std'],
                         time=observation['time'], length=context['length'],loop=context.get('loop',False))
        self.registered_time=observation['time']
        self.state = dict(status='locked', identity=key, key=context['key'], visit=self.visit,
                          progress_x=progress, progress_std=first['std'], block_instance=block,
                          loop_cycle=self.cycle, absolute_progress=self.odometer_base+progress,
                          localized=first['std'] <= .5, confidence=first['score'])
        return self.state

    def projected(self, observation):
        value = self.state.copy()
        predicted = self.predict(observation)
        if predicted and self.state.get('status') in ('locked', 'tracked','identified'):
            value.update(progress_x=predicted['progress'], progress_std=predicted['std'],
                         localized=self.state.get('status')!='identified'and predicted['std'] <= .5)
        else:
            value['localized'] = False
        return value
