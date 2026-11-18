"""Visual map context and conservative fixed-board order, including random gaps."""


def map_sequences(catalog):
    result=[]
    for level in catalog['levels']:
        for ref in level['maps']:
            world=catalog['maps'][str(ref['id'])]
            pools=[s['pool']for s in world['slots']]+([world['loop']]if world.get('loop')else[])
            result.append(dict(level=level['id'],map=ref['id'],slots=[dict(
                slot=i,fixed=[v['id']for v in pool if v['classification']['layout']=='fixed'],
                random=any(v['classification']['layout']!='fixed'for v in pool),
                loop=i>len(world['slots']))for i,pool in enumerate(pools,1)]))
    return result


class BoardSequence:
    def __init__(self,sequences):
        self.maps={(m['level'],m['map']):m for m in sequences}
        self.level=None
        self.slot=None
        self.place=None
        self.confirmed=None
        self.near_exit=False
        self.pending=None
        self.count=0
        self.history=[]

    def begin(self,level,slot):
        self.level,self.slot=level,slot

    def may_change_map(self,place):
        if self.confirmed is None:return self.level is None or place[0]==self.level
        if place==self.confirmed[:2]:return True
        world=self.maps.get(self.confirmed[:2])
        return bool(world and self.near_exit and self.slot==len(world['slots'])
                    and place[0]==self.level+1)

    def background(self,scores):
        # Background supplies only the map, never a board ID or world X.
        ranked=sorted(((score,place)for place,score in scores.items()
                       if self.may_change_map(place)),reverse=True)
        if not ranked or ranked[0][0]<.65 or len(ranked)>1 and ranked[0][0]-ranked[1][0]<.12:
            self.pending=None;self.count=0
            return
        place=ranked[0][1]
        self.count=self.count+1 if self.pending==place else 1
        self.pending=place
        if self.count>=3:
            if self.confirmed is not None and place!=self.confirmed[:2]:
                self.level,self.slot=place[0],1
                self.confirmed=None;self.near_exit=False
                self.history.append(dict(level=place[0],map=place[1],slot=1,status='map_background'))
            self.place=place

    def permits(self,identity):
        level,world,slot,stage=identity
        if self.level is not None and level!=self.level:return False
        if self.place is not None and (level,world)!=self.place:return False
        info=self.maps.get((level,world))
        if info is None:return False
        slots=info['slots']
        if not 1<=slot<=len(slots)or stage not in slots[slot-1]['fixed']:return False
        if self.slot is None:return True
        if slot<self.slot:return False
        if slot==self.slot:return self.confirmed is None or identity==self.confirmed
        if self.confirmed is not None and not self.near_exit:return False
        # No random variant is identified. A later distinctive fixed board can
        # resolve a forward hypothesis only through slots that may be random;
        # an unseen fixed-only slot is never silently skipped.
        first=self.slot if self.confirmed is None else self.slot+1
        return all(slots[i-1]['random']for i in range(first,slot))

    def accept(self,identity,progress,length):
        if not self.permits(identity):return
        if identity!=self.confirmed:
            old=self.slot
            if old is not None:
                first=old if self.confirmed is None else old+1
                for slot in range(first,identity[2]):
                    self.history.append(dict(level=identity[0],map=identity[1],slot=slot,
                                             status='unobserved_random_possible'))
            self.level,self.slot,self.place=identity[0],identity[2],identity[:2]
            self.confirmed=identity
            self.history.append(dict(level=identity[0],map=identity[1],slot=identity[2],
                                     stage=identity[3],status='fixed_visual'))
        self.near_exit=progress>=length-18

    def state(self):
        return dict(level=self.level,map=self.place[1]if self.place else None,slot=self.slot,
                    near_exit=self.near_exit,history=self.history[-12:])
