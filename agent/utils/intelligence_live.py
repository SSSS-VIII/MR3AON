"""Live observation/state adapter. No screenshots, OCR calls, ADB or controller input."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import unicodedata

from intelligence_strategy.model import CARDS,BY_NAME,build_engine
from intelligence_strategy.tuned import analyze_tuned,resolve_policy
from .intelligence_cards import box_xywh,SLOTS

GRID_X=(142,313,485)
GRID_Y=(222,412,605)


def normalize(text):
    return re.sub(r'[^\w\u4e00-\u9fff]','',unicodedata.normalize('NFKC',text)).replace('仓牙','苍牙').replace('凤林','风林')


_NAMES={normalize(c['name']):c['name'] for c in CARDS}
_NAMES['轮回戒指']='轮回之戒'


def card_name(text):
    key=normalize(text)
    if key in _NAMES:return _NAMES[key]
    # Only a unique single-character OCR error on a full name. Never guess a variant from 小黑/琳.
    if len(key)<3:return None
    matches=set()
    for known,name in _NAMES.items():
        if len(known)<4 or abs(len(key)-len(known))>1:continue
        if len(key)==len(known):distance=sum(a!=b for a,b in zip(key,known))
        else:
            short,long=(key,known) if len(key)<len(known) else (known,key)
            distance=1 if any(long[:i]+long[i+1:]==short for i in range(len(long))) else 2
        if distance<=1:matches.add(name)
    return next(iter(matches)) if len(matches)==1 else None


def shop_slot(box):
    x,y,w,h=box_xywh(box);cx,cy=x+w/2,y+h/2
    row=0 if 350<=cy<=405 else 1 if 575<=cy<=615 else -1
    col=0 if 640<=cx<825 else 1 if 825<=cx<1020 else 2 if 1020<=cx<1220 else -1
    return row*3+col if row>=0 and col>=0 and not (row==1 and col==2) else None


def cell_index(box):
    x,y,w,h=box_xywh(box);cx,cy=x+w/2,y+h/2
    col=min(range(3),key=lambda i:abs(cx-GRID_X[i]));row=min(range(3),key=lambda i:abs(cy-GRID_Y[i]))
    return row*3+col if abs(cx-GRID_X[col])<=80 and abs(cy-GRID_Y[row])<=85 else None


def observation(items,empty_boxes):
    hand={};visible=set();gold=[];unlabelled_gold=[];refreshes=[];health=[]
    for text,box in items:
        x,y,w,h=box_xywh(box);cx,cy=x+w/2,y+h/2
        slot=shop_slot(box)
        if slot is not None and len(re.findall(r'[\u4e00-\u9fffA-Za-z]',text))>=2:
            visible.add(slot)
            name=card_name(text)
            if name:
                if slot in hand and hand[slot]!=name:hand[slot]=None
                else:hand.setdefault(slot,name)
        normalized=unicodedata.normalize('NFKC',text)
        if 1100<=cx<=1260 and 145<=cy<=200:
            # Purchase animations such as -2 are not wallet balances. Prefer
            # the labelled balance, including when OCR merges it with -2.
            balance=re.search(r'金币\s*:?\s*(\d+)',normalized)
            if balance:gold.append(int(balance[1]))
            elif re.fullmatch(r'\s*\d+\s*',normalized):unlabelled_gold.append(int(normalized))
        if 1040<=cx<=1250 and 500<=cy<=565 and '已刷新' in text:refreshes.append(0)
        if 1040<=cx<=1250 and 570<=cy<=615 and '刷新' in text:
            remaining=re.findall(r'\d+',text.translate(str.maketrans({'O':'0','o':'0','I':'1','l':'1'})))
            if remaining:refreshes.append(int(remaining[-1]))
        if 1135<=cx<=1220 and 40<=cy<=85:
            value=re.sub(r'[^0-9]','',text.translate(str.maketrans({'O':'0','o':'0','I':'1','l':'1'})))
            if value and int(value)<=100:health.append(int(value))
    unique=lambda values:next(iter(set(values))) if len(set(values))==1 else None
    return {'hand':{slot:name for slot,name in hand.items() if name},'visible_slots':visible,
            'gold':unique([n for n in (gold or unlabelled_gold) if 0<=n<=100]),
            'refreshes':0 if 0 in refreshes else unique([n for n in refreshes if 0<=n<=9]),'health':unique(health),
            'empty':{i for box in empty_boxes if (i:=cell_index(box)) is not None}}


class IntelligenceSession:
    def __init__(self,path=None):
        self.path=Path(path) if path else None
        self.board=[None]*9;self.round=0;self.valid=False;self.pending=None;self.disabled=False
        self.reason='cold_resume';self.gold=None
        if self.path and self.path.exists():
            try:
                data=json.loads(self.path.read_text())
                if data.get('version')==1 and len(data['board'])==9 and all(c is None or c['name'] in BY_NAME for c in data['board']):
                    self.board=data['board'];self.round=data['round'];self.valid=data['valid'];self.pending=data.get('pending')
                    self.reason=data.get('reason','restored');self.gold=data.get('gold')
            except (OSError,ValueError,KeyError,TypeError):pass

    def save(self):
        if not self.path:return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version':1,'board':self.board,'round':self.round,'valid':self.valid,
                                         'pending':self.pending,'reason':self.reason,'gold':self.gold},ensure_ascii=False)+'\n')
        temporary.replace(self.path)

    def reset(self):
        self.board=[None]*9;self.round=0;self.valid=True;self.pending=None;self.gold=None;self.reason='new_match';self.save()

    def warm(self):
        try:
            build_engine();self.disabled=False
        except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as error:
            self.disabled=True;self.reason=f'kernel_unavailable:{type(error).__name__}'
        return not self.disabled

    def confirm(self,seen,round_number):
        if not self.pending:return True
        pending=self.pending;self.pending=None
        if round_number!=pending['round'] or seen['gold'] is None:
            self.valid=False;self.reason='unconfirmed_round_or_gold';self.save();return False
        successful=[a for a in pending['actions'] if a['cell'] not in seen['empty'] and a['shop_slot'] not in seen['visible_slots']]
        spent=sum(BY_NAME[a['card']]['cost'] for a in successful)
        if pending['gold']-seen['gold']!=spent:
            self.valid=False;self.reason='placement_receipt_mismatch';self.save();return False
        self.gold=seen['gold']
        for a in successful:self.board[a['cell']]={'name':a['card'],'entered_round':round_number}
        self.save();return True

    def prepare(self,seen,round_number,refreshes, *, planner=analyze_tuned):
        if self.pending:self.confirm(seen,round_number)
        if round_number<self.round:
            self.board=[None]*9;self.valid=False;self.reason='round_rewound'
        if round_number==1 and seen['gold']==5 and len(seen['empty'])>=7:
            self.reset()
        if any(c is not None and i in seen['empty'] for i,c in enumerate(self.board)):
            self.valid=False;self.reason='occupied_cell_became_empty'
        if round_number==self.round and self.gold is not None and seen['gold'] is not None and seen['gold']!=self.gold:
            self.valid=False;self.reason='unexpected_same_round_payment'
        self.round=round_number;self.gold=seen['gold']
        available=min(refreshes,seen['refreshes']) if seen['refreshes'] is not None else refreshes
        after='refresh' if available and seen['visible_slots'] else 'prepare'
        if seen['gold'] is None:
            return {'actions':[],'next_action':after,'mode':'skip_unknown_gold'}
        slots=sorted(seen['hand']);hand=[seen['hand'][i] for i in slots]
        if self.valid and not self.disabled:
            try:
                raw={'round':round_number,'gold':seen['gold'],'board':self.board,'shop_slots':len(seen['visible_slots'])}
                plan=planner(raw,hand,available,policy={'prioritize_finish':True},cumulative_damage=100-seen['health'] if seen['health'] is not None else (100 if round_number>=3 else 0))
                plan['mode']='scored'
                for action in plan['actions']:action['shop_slot']=slots[action['shop_slot']]
            except (OSError,RuntimeError,ValueError,KeyError,subprocess.SubprocessError) as error:
                self.reason=f'planning_fallback:{type(error).__name__}';plan=self.fallback(seen,round_number,available)
        else:plan=self.fallback(seen,round_number,available)
        if plan['actions']:
            self.pending={'round':round_number,'gold':seen['gold'],'actions':deepcopy(plan['actions']),'after':plan['next_action']}
        self.save();return plan

    def fallback(self,seen,round_number,refreshes):
        from .intelligence_cards import ROLES
        gold=seen['gold'];cells=iter(sorted(seen['empty']));actions=[]
        for slot,name in sorted(seen['hand'].items()):
            if not ROLES.search(name) or BY_NAME[name]['cost']>gold:continue
            cell=next(cells,None)
            if cell is None:break
            actions.append({'shop_slot':slot,'card':name,'cell':cell});gold-=BY_NAME[name]['cost']
        return {'actions':actions,'next_action':'refresh' if refreshes and len(seen['visible_slots'])>len(actions) else 'prepare',
                'mode':'fallback','reason':self.reason}


def click_plans(actions):
    return [(SLOTS[a['shop_slot']],(GRID_X[a['cell']%3],GRID_Y[a['cell']//3]),a['card']) for a in actions]
