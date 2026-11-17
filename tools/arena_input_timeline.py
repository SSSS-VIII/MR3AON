"""Optional action timeline for delayed pixels and acknowledged own inputs.

No device/native/model access and no image-age constant. Reuses original
Perception.action and advance_player unchanged.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import math
from arena_vision import Box,Perception,advance_player
import arena_motion as motion

# The saved action target is strictly a subset of an already pixel-derived
# observation. Tracks, labels, native state, model objects and image codes are
# deliberately excluded. Geometry remains immutable inside the event JSON.
PIXEL_FIELDS=frozenset(('time','player','phase','jumps','motion','rope','rope_segment','rope_segments',
    'terrain','scale_px','stand_w','stand_h','vy','vx','scene_velocity_x','scene_motion_observed',
    'visible_supports','blocking_faces','ground_contact_observed','rope_contact_observed',
    'down_action_end_observed','player_predicted','ground_down_collider_restore','pending_rope_clamp','rope_down_anchor'))
ACTION_FIELDS=('jump_count','last_action','last_flip','active_motion','motion_origin')
KEY_FOR_PRIMITIVE={'jump1':'jump','jump2':'jump','rope_up':'jump','air_up':'jump',
                   'rope_down':'down','air_down':'down','slide':'slide'}


def stamp(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError('Timestamp must be finite')
    return result


def freeze_pixels(observation):
    result={key:observation[key]for key in PIXEL_FIELDS if key in observation}
    if result.get('player')is not None:
        p=result['player'];result['player']=[p.x,p.y,p.w,p.h]
    return json.dumps(result,allow_nan=False,sort_keys=True,separators=(',',':'))


def thaw_pixels(payload):
    result=json.loads(payload)
    if result.get('player')is not None:result['player']=Box(*result['player'])
    result['tracks']=[]
    return result


def contact_seen(observation):
    return not observation.get('player_predicted',False) and any(observation.get(key,False)for key in
        ('ground_contact_observed','rope_contact_observed','down_action_end_observed'))


@dataclass(frozen=True)
class OwnInput:
    event_id: int
    action: str
    primitive: str|None
    enqueued_time: float
    estimated_consumption: float
    _planned_pixels: str

    @property
    def planned(self):return thaw_pixels(self._planned_pixels)


@dataclass
class ActionCursor:
    """Only fields Perception.action reads/writes; no detector or tracker copy."""
    jump_count: int
    last_action: float
    last_flip: float
    active_motion: dict|None
    motion_origin: dict|None
    visual_role: bool
    body_height: float
    last_observation: dict|None=None

    @classmethod
    def from_perception(cls,perception):
        return cls(**{key:deepcopy(getattr(perception,key))for key in ACTION_FIELDS},
                   visual_role=perception.visual_role,body_height=perception.body_height)

    def install(self,perception):
        for key in ACTION_FIELDS:setattr(perception,key,deepcopy(getattr(self,key)))

    def copy(self):return deepcopy(self)

    def action(self,event,current):
        # The production implementation continues to choose the physical
        # meaning of jump/down, including finite-support primitive fallback.
        Perception.action(self,event.action,event.estimated_consumption,current,
                          primitive=event.primitive,source_observation=event.planned)


def advance(state,target,*,forecast_contact):
    target=stamp(target)
    if target<state['time']:raise ValueError('Cannot replay backwards')
    dt=target-state['time']
    if dt==0:return dict(state)
    current=advance_player(state,dt,predict_contact=forecast_contact)
    # Any extrapolation is not a new observed contact, even when the base
    # image was genuinely standing. Preserve its age separately in metadata.
    for key in ('ground_contact_observed','rope_contact_observed','down_action_end_observed'):
        current[key]=False
    if not forecast_contact:
        ended=state.get('motion')is not None and current.get('motion')is None
        reduced=current.get('jumps',0)<state.get('jumps',0)
        original=state.get('motion')
        protected=original and (motion.is_rope_transition(original['name'])or original['name'].startswith('jump'))
        if reduced or ended and protected:
            current.update(jumps=state.get('jumps',0),contact_unconfirmed=True)
            current.pop('landing_predicted',None)
            if protected:
                active=dict(original)
                if motion.is_rope_transition(active['name']):active.update(requires_contact=True,contact_pending=True)
                current.update(motion=active,phase=motion.phase(active['name'],target-active['started'],active))
    return current


def apply_event(cursor,state,event,*,forecast_contact):
    current=advance(state,event.estimated_consumption,forecast_contact=forecast_contact)
    before_ledger=cursor.jump_count
    cursor.action(event,current)
    if not forecast_contact and not contact_seen(current) and cursor.jump_count<before_ledger:
        # A predicted landing may explain a submitted jump, but cannot certify
        # a reset of the actual observed jump budget before seeing contact.
        cursor.jump_count=before_ledger
        current=dict(current,contact_unconfirmed=True)
    active=cursor.active_motion
    if active is None:
        phase=current['phase']
    else:
        phase=motion.phase(active['name'],max(0,event.estimated_consumption-active['started']),active)
    result=dict(current,motion=deepcopy(active),jumps=cursor.jump_count,phase=phase,
                last_input_time=event.estimated_consumption)
    if current.get('contact_unconfirmed'):result['input_contact_unconfirmed']=True
    return result,dict(event_id=event.event_id,primitive=event.primitive,
                       resolved_primitive=(active or{}).get('name'),
                       contact_unconfirmed=bool(result.get('input_contact_unconfirmed')),
                       support_unconfirmed=bool((active or{}).get('support_unconfirmed')))


class OwnInputTimeline:
    def __init__(self,perception):
        self.perception=perception
        self.reset()

    def reset(self):
        self._events=[];self.consumed=0;self.latest=None;self.observed_cursor=None
        self.replay_geometry=None
        self.prepared_stamp=None;self.prepared_cursor=None;self.prepared_prediction=None;self.failed=False
        self._next_id=1;self.last_receipts=[]

    @property
    def events(self):return tuple(self._events)

    def _ready(self):
        if self.failed:raise RuntimeError('Observation failed; reset at an explicit episode boundary')
        if self.prepared_stamp is not None:raise RuntimeError('Complete the prepared observation first')

    def record(self,action,ack,*,primitive=None,planned=None,input_delay=1/60):
        self._ready()
        if self.latest is None:raise RuntimeError('Need an initial pixel observation')
        if action not in ('jump','down','slide'):raise ValueError('Unsupported own key')
        if primitive is not None and KEY_FOR_PRIMITIVE.get(primitive)!=action:
            raise ValueError('Primitive must match the submitted physical key')
        delay=stamp(input_delay)
        if delay<0:raise ValueError('Input prior cannot be negative')
        enqueued=stamp(ack.device_ready_ns/1e9);consumption=enqueued+delay
        if consumption<self.latest['time']:raise ValueError('Input predates observed cursor')
        if self.events and consumption<self.events[-1].estimated_consumption:
            raise ValueError('ACK event order must be monotonic')
        event=OwnInput(self._next_id,action,primitive,enqueued,consumption,freeze_pixels(planned or self.latest))
        self._next_id+=1;self._events.append(event)
        return event

    def before_observe(self,image_stamp):
        self._ready();image_stamp=stamp(image_stamp)
        if self.latest is not None and image_stamp<=self.latest['time']:
            raise ValueError('Fresh image timestamps must strictly increase; repeated CRC uses project')
        cursor=(self.observed_cursor.copy()if self.observed_cursor is not None else ActionCursor.from_perception(self.perception))
        state=self.latest;index=self.consumed;receipts=[]
        if state is not None and state.get('player') is None:
            state=self.replay_geometry
        if state is not None:
            while index<len(self.events)and self.events[index].estimated_consumption<=image_stamp:
                state,receipt=apply_event(cursor,state,self.events[index],forecast_contact=False)
                receipts.append(receipt);index+=1
        # Install before the real observe starts: ROI missing-role prediction,
        # slide-root support query, tracker and _finish all see the right phase.
        cursor.install(self.perception)
        self.consumed=index;self.prepared_stamp=image_stamp;self.prepared_cursor=cursor.copy()
        self.last_receipts=receipts
        self.prepared_prediction=(advance(state,image_stamp,forecast_contact=False)if state is not None else None)
        if self.prepared_prediction is not None:
            self.prepared_prediction.update(player_predicted=True,source_image_stamp=self.latest['time'])
        return tuple(receipts)

    def after_observe(self,observation,*,capture_return_stamp=None):
        if self.prepared_stamp is None:raise RuntimeError('No observation was prepared')
        if stamp(observation['time'])!=self.prepared_stamp:raise ValueError('Observer returned a different image time')
        returned=self.prepared_stamp if capture_return_stamp is None else stamp(capture_return_stamp)
        if returned<self.prepared_stamp:raise ValueError('Capture cannot return before its image time')
        result=dict(observation,capture_return_stamp=returned,image_stamp=self.prepared_stamp)
        prior=self.prepared_cursor
        if result.get('jumps',0)<prior.jump_count and not contact_seen(result):
            result['jumps']=prior.jump_count;result['contact_unconfirmed']=True
            self.perception.jump_count=prior.jump_count
            if result.get('motion')is None and prior.active_motion:
                active=dict(prior.active_motion)
                if motion.is_rope_transition(active['name']):active.update(requires_contact=True,contact_pending=True)
                result.update(motion=active,phase=motion.phase(active['name'],result['time']-active['started'],active))
                self.perception.active_motion=deepcopy(active)
        self.perception.last_observation=result
        if result.get('player') is not None:
            self.replay_geometry=result
        elif self.prepared_prediction is not None:
            # A queued key still happened even when the next image has no
            # detectable body. Keep geometry only for replaying that own key;
            # never expose this expired estimate as a policy-visible player.
            prediction=self.prepared_prediction
            delta=result.get('camera_reference_y',0.)-prediction.get('camera_reference_y',0.)
            p=prediction['player']
            self.replay_geometry=dict(result,player=Box(p.x,p.y+delta,p.w,p.h),
                phase=prediction['phase'],motion=deepcopy(self.perception.active_motion),
                player_predicted=True,input_geometry_unconfirmed=True,
                ground_contact_observed=False,rope_contact_observed=False,down_action_end_observed=False)
        self.latest=result;self.observed_cursor=ActionCursor.from_perception(self.perception)
        self.prepared_stamp=None;self.prepared_cursor=None;self.prepared_prediction=None
        return result

    def missing_role_context(self):
        """Explicit adapter input; never replace last actual pixel observation.

        The live OBB adapter needs to request this instead of the old
        last_observation when its full-frame/ROI player is absent. Do not
        combine a camera-shifted forecast with the subsequent full camera
        correction. Motion replay stays in the last image camera plane; the
        OBB observer adds the measured camera delta once after support fitting.
        """
        if self.prepared_stamp is None:raise RuntimeError('Only available inside a prepared observation')
        current=self.prepared_prediction
        if current is None:return None,'no_previous_pixels'
        if current.get('camera_reference_y') != self.latest.get('camera_reference_y'):
            return None,'camera_reference_changed_during_forecast'
        context=deepcopy({k:v for k,v in current.items()if k!='tracks'})
        context['tracks']=[]
        return context,None

    def observe(self,rgba,image_stamp,*,capture_return_stamp=None,observer=None):
        self.before_observe(image_stamp)
        try:
            result=(observer or self.perception.observe)(rgba,image_stamp)
            return self.after_observe(result,capture_return_stamp=capture_return_stamp)
        except Exception:
            self.failed=True
            raise

    def project(self,target_stamp,*,predict_contact=False,include_tracks=True):
        self._ready()
        if self.latest is None:raise RuntimeError('Need an initial pixel observation')
        target_stamp=stamp(target_stamp)
        if target_stamp<self.latest['time']:raise ValueError('Cannot project before observed image')
        cursor=self.observed_cursor.copy();state=dict(self.latest);receipts=[]
        missing=state.get('player') is None
        if missing and self.replay_geometry is not None:state=dict(self.replay_geometry)
        for event in self.events[self.consumed:]:
            if event.estimated_consumption>target_stamp:break
            state,receipt=apply_event(cursor,state,event,forecast_contact=predict_contact)
            receipts.append(receipt)
        result=advance(state,target_stamp,forecast_contact=predict_contact)
        # Hazard trajectories still use their original image clock once. Own
        # keys do not cause arbitrary incremental re-fitting of track history.
        age=target_stamp-self.latest['time']
        result['tracks']=([track.at(age)for track in self.latest.get('tracks',[])]
                          if include_tracks else [])
        result.update(observation_age_ms=age*1000,source_image_stamp=self.latest['time'],
                      replayed_event_ids=[r['event_id']for r in receipts],replayed_events=receipts)
        if missing:
            result.update(player=None,phase='unknown',input_geometry_unconfirmed=True)
        return result
