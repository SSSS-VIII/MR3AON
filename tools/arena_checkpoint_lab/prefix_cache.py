"""Bounded ownership of exact VM-prefix nodes within one guided window."""


class PrefixCache:
    def __init__(self,max_points=96):
        self.max_points=max_points
        self.context=None
        self.transitions={}
        self.points=set()
        self.unsafe=set()
        self.decisions={}
        self.observations={}
        self.margin_feedback=[]

    def bind(self,root,start,offset,horizon,last_input_frame):
        context=(root,id(start),offset,horizon,last_input_frame)
        if self.context is not None and self.context!=context:
            raise ValueError('Prefix cache belongs to another original VM search root')
        self.context=context

    def remember(self,parent,action,row):
        if len(self.points)>=self.max_points:return False
        self.transitions[parent,action]=row
        self.points.add(row['point'])
        return True

    def close(self,gate,keep=()):
        for point in self.points-set(keep):gate.drop(point)
        self.points.clear();self.transitions.clear();self.unsafe.clear();self.decisions.clear();self.observations.clear()
        self.margin_feedback.clear()
