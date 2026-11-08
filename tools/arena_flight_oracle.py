"""Original ProcessMovementOnGround in a flat, no-platform, no-input fixture.

Unity terrain queries and effect/UI calls are explicit test substitutes. This
is an oracle fixture, not a replacement for game terrain or visual rendering.
"""
import struct
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X2, UC_ARM64_REG_W1,
    UC_ARM64_REG_S0, UC_ARM64_REG_S1, UC_ARM64_REG_S2, UC_ARM64_REG_SP, UC_ARM64_REG_LR)


def flat_flight(oracle, ninja_data, *, position, velocity, initial_state=14,
                fixed_dt=.02, ground_y=0, frames=160):
    if len(ninja_data)!=24:raise ValueError('Expected 24 scalar NinjaData fields')
    state=[initial_state];pos=list(position);events=[];jump_points=[]
    def s(u,r,v):u.reg_write(r,struct.unpack('<I',struct.pack('<f',v))[0])
    def ret(u,v):u.reg_write(UC_ARM64_REG_X0,v)
    def vec(u,values):
     for r,v in zip([UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2],values):s(u,r,v)
    def getpos(u):vec(u,pos)
    def setpos(u):pos[:]=[struct.unpack('<f',struct.pack('<I',u.reg_read(r)))[0] for r in [UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2]]
    def setstate(u):state[0]=u.reg_read(UC_ARM64_REG_W1)
    def ground(u):s(u,UC_ARM64_REG_S0,ground_y);u.mem_write(u.reg_read(UC_ARM64_REG_X2),b'\0'*8)
    def rotation(u):events.append(('local_rotation',u.reg_read(UC_ARM64_REG_W1)))
    hooks={0x49c6104:lambda u:ret(u,0),0x49c4590:lambda u:ret(u,0),0x49c462c:lambda u:ret(u,0),0x4c548b0:lambda u:ret(u,0x10009000),0x4c7b284:lambda u:events.append("left_btn_state"),0x4c7b070:lambda u:events.append("right_btn_state"),0x49c63b8:lambda u:None,0x4a0d7c0:lambda u:events.append('fall_smoke'),0x4a16ed0:lambda u:ret(u,0),
     0x4a0bbac:lambda u:ret(u,0),0x5517f08:lambda u:ret(u,0x10006000),
     0x43ad9a8:lambda u:events.append(('audio',u.reg_read(UC_ARM64_REG_W1))),
     0x49c8b88:lambda u:vec(u,jump_points[-1] if jump_points else (0,0,0)),
     0x4a02610:lambda u:events.append('fall_need_roll'),0x49d8cd8:lambda u:ret(u,0),0x49c8c0c:lambda u:jump_points.append(tuple(pos)),0x10008200:lambda u:events.append(("scarf_roll",u.reg_read(UC_ARM64_REG_W1))),0x6b4d14c:rotation,0x49c629c:lambda u:None,0x49c621c:lambda u:ret(u,0),0x49c3268:lambda u:ret(u,state[0]),0x49c32e8:setstate,
     0x6b4cc20:getpos,0x6b4ccc0:setpos,0x49c57bc:lambda u:ret(u,0x10004000),
     0x49c6338:lambda u:ret(u,0),0x48efee0:ground,0x48e5608:lambda u:vec(u,(10,0,0)),
     0x49c7c2c:lambda u:ret(u,0),0x49c3ed4:lambda u:s(u,UC_ARM64_REG_S0,-25),
     0x6b484d8:lambda u:s(u,UC_ARM64_REG_S0,fixed_dt),0x6b48370:lambda u:s(u,UC_ARM64_REG_S0,fixed_dt),
     0x4a7bc90:lambda u:ret(u,0x10005000),0x5517a18:lambda u:ret(u,0x10006000),
     0x4842cb8:lambda u:ret(u,1),0x10008000:lambda u:ret(u,0x10006000)}
    globs=[0x718dd28,0x7193100,0x718b540,0x718b250,0x718e348,0x718da10,0x71d7950,0x71e1110,0x718e3d8,0x718e410]
    u,q,f=oracle._machine(0x49d8ed8,0x49dc7ac,globs,0x7692734,hooks)
    for a in range(0x11b0000,0x11b8000,8):q(a,int.from_bytes(oracle.library[a:a+8],'little'))
    q(0x768294a,1)
    obj=0x10000000;klass=0x10007000;data=0x10003000
    q(obj,klass);q(klass+0xd28,0x10008200);q(klass+0xb98,0x10008000);q(obj+0x190,data);q(obj+0x268,0x10005000);q(obj+0x420,0x10006000)
    f(0x10006000+0x1a4,100000)
    for off,v in zip([0x138,0x13c,0x140],velocity):f(obj+off,v)
    for i,v in enumerate(ninja_data):f(data+0x10+i*4,v)
    history=[]
    for frame in range(frames):
     u.reg_write(UC_ARM64_REG_X0,obj);u.reg_write(UC_ARM64_REG_SP,0x2000ff00);u.reg_write(UC_ARM64_REG_LR,0x1001f000)
     gravity=oracle.gravity(state[0],fourth_jump=False,data=ninja_data)
     hooks[0x49c3ed4]=lambda u:s(u,UC_ARM64_REG_S0,gravity)
     u.emu_start(0x49d8ed8,0x1001f000,count=20000)
     history.append({'frame':frame,'state':state[0],'position':list(pos),
                     'velocity':[struct.unpack('<f',u.mem_read(obj+off,4))[0] for off in [0x138,0x13c,0x140]]})
     if state[0]==5:break
    return {'frames':history,'jump_points':jump_points,'events':events}
