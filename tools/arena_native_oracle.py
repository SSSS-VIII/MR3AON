#!/usr/bin/env python3
"""Offline ARM64 oracle for two recovered client methods, not a game runtime.

Runs only a local library copy in Unicorn. Unity calls and game context are
explicit fixtures. Never opens a device/process or imports Android controllers.
Addresses apply to the recorded client revision only.
"""
from __future__ import annotations
import hashlib
import struct
from pathlib import Path

LIBRARY_SHA256 = '08cc44d9d8c8edf397fa886335ffd04897ab1b8ab1d3ddd44c4ba788afa0d9b0'


class NativeOracle:
    def __init__(self, library: Path):
        self.library = library.read_bytes()
        if hashlib.sha256(self.library).hexdigest() != LIBRARY_SHA256:
            raise ValueError('Unsupported client library: re-establish method addresses first')

    def _machine(self, start, end, globals_, flag, hooks):
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_LR
        u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        pages = set()
        def map_at(address, length=8):
            for page in range(address & ~4095, (address + length + 4095) & ~4095, 4096):
                if page not in pages:
                    u.mem_map(page,4096);pages.add(page)
        def put(address, data):
            map_at(address,len(data));u.mem_write(address,data)
        def q(address, value):put(address,struct.pack('<Q',value))
        def f(address, value):put(address,struct.pack('<f',value))
        # Recovered executable PT_LOAD has vaddr - file_offset = 0x4000.
        put(start,self.library[start-0x4000:end-0x4000])
        map_at(0x10000000,0x20000)
        map_at(0x20000000,0x10000)
        for i,address in enumerate(globals_):
            slot=0x10010000+i*0x1000;klass=slot+0x100;statics=slot+0x300
            q(address,slot);q(slot,klass);q(klass+0xb8,statics)
            put(klass+0xe0,struct.pack('<I',1))
        put(flag,b'\1')
        for address in hooks:put(address,b'\xc0\x03\x5f\xd6') # ret
        def call(uc,address,size,data):
            if address in hooks:hooks[address](uc)
        u.hook_add(UC_HOOK_CODE,call)
        u.reg_write(UC_ARM64_REG_SP,0x2000ff00)
        u.reg_write(UC_ARM64_REG_LR,0x1001f000)
        return u,q,f

    def collider(self, animation_state, *, radius=.2, height=1.8,
                 center=(.1,0,0), mounted=False, capsule_present=True,
                 parameters=None):
        from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_W1
        from unicorn.arm64_const import UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2
        values={'radius':radius,'height':height,'center':tuple(center)};calls=[]
        def scalar(key):
            def apply(u):
                values[key]=struct.unpack('<f',struct.pack('<I',u.reg_read(UC_ARM64_REG_S0)))[0]
                calls.append(key)
            return apply
        def position(u):
            values['center']=tuple(struct.unpack('<f',struct.pack('<I',u.reg_read(r)))[0]
                                   for r in [UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2])
            calls.append('center')
        hooks={0x6b3b1ec:lambda u:u.reg_write(UC_ARM64_REG_X0,int(not capsule_present)),
               0x6c00d24:lambda u:u.reg_write(UC_ARM64_REG_X0,int(mounted)),
               0x6c021f4:position,0x6c022c8:scalar('radius'),0x6c02350:scalar('height')}
        start=0x4a3a590
        u,q,f=self._machine(start,0x4a3a778,[0x71e16d0,0x718b250],0x7692b4d,hooks)
        obj=0x10000000;q(obj+0x80,0x10001000 if capsule_present else 0);q(obj+0x88,0x10002000)
        # Runtime FieldInfo offsets, not guessed compact-layout offsets.
        p=parameters or {}
        for off,name,default in [(0x28,'normal_radius',.2),(0x2c,'normal_height',1.8),
                                 (0x30,'roll_radius',.1),(0x34,'roll_height',.1),(0x38,'jump_height',1.2)]:f(obj+off,p.get(name,default))
        for off,name,default in [(0x3c,'roll_center',(.05,0,0)),(0x48,'slide_center',(.05,-.3,0)),
                                 (0x54,'normal_center',(.1,0,0)),(0x60,'jump_center',(.1,.3,0))]:
            for i,v in enumerate(p.get(name,default)):f(obj+off+i*4,v)
        u.reg_write(UC_ARM64_REG_X0,obj);u.reg_write(UC_ARM64_REG_W1,animation_state)
        u.emu_start(start,0x1001f000,count=5000)
        return {**values,'calls':calls}

    def platform(self, *, moving, remaining, speed_x, speed_y, trigger_distance,
                 bounds, position, role_x, direction, fixed_dt):
        from unicorn.arm64_const import UC_ARM64_REG_X0
        from unicorn.arm64_const import UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2
        def s(u,r,value):u.reg_write(r,struct.unpack('<I',struct.pack('<f',value))[0])
        pos=list(position)
        def get_pos(u):
            for r,v in zip([UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2],pos):s(u,r,v)
        def set_pos(u):
            pos[:]=[struct.unpack('<f',struct.pack('<I',u.reg_read(r)))[0] for r in [UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_S2]]
        hooks={0x4884c0c:lambda u:None, # Base object update excluded from this reducer oracle.
               0x483ba68:lambda u:u.reg_write(UC_ARM64_REG_X0,0x10005000),
               0x4842cb8:lambda u:u.reg_write(UC_ARM64_REG_X0,direction&0xffffffffffffffff),
               0x5517a18:lambda u:u.reg_write(UC_ARM64_REG_X0,0x10005000),
               0x4a0d980:lambda u:s(u,UC_ARM64_REG_S0,role_x),
               0x6b484d8:lambda u:s(u,UC_ARM64_REG_S0,fixed_dt),
               0x4a7bc90:lambda u:u.reg_write(UC_ARM64_REG_X0,0x10006000),
               0x6b4cc20:get_pos,0x6b4ccc0:set_pos}
        start=0x48849e8
        u,q,f=self._machine(start,0x4884c0c,[0x71d4f10,0x718b1f8,0x718da10],0x76916ed,hooks)
        obj=0x10000000;info=0x10003000
        q(obj+0x1a0,info);u.mem_write(obj+0x198,bytes([bool(moving)]))
        for i,v in enumerate(bounds):f(info+0x10+i*4,v)
        for off,v in [(0x24,speed_x),(0x28,speed_y),(0x2c,trigger_distance),(0x30,remaining)]:f(info+off,v)
        u.reg_write(UC_ARM64_REG_X0,obj);u.emu_start(start,0x1001f000,count=5000)
        def read_f(address):return struct.unpack('<f',u.mem_read(address,4))[0]
        return {'moving':bool(u.mem_read(obj+0x198,1)[0]),'remaining':read_f(info+0x30),
                'bounds':tuple(read_f(info+0x10+i*4) for i in range(4)),'position':tuple(pos)}

    def gravity(self, physics_state, *, fourth_jump, data):
        """Execute Ninja.UpdateGravity; data is 24 original NinjaData float fields."""
        from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_W0
        if len(data)!=24:raise ValueError('Expected 24 NinjaData scalar fields')
        start=0x49d0500
        hooks={0x49c3268:lambda u:u.reg_write(UC_ARM64_REG_W0,physics_state&0xffffffff)}
        u,q,f=self._machine(start,0x49d0664,[0x718dd28],0x769271f,hooks)
        # Jump table is original read-only program data, not regenerated cases.
        address=0x11b59da
        table=self.library[address:address+54]
        for i in range(0,len(table),8):q(address+i,int.from_bytes(table[i:i+8].ljust(8,b'\0'),'little'))
        obj=0x10000000;ninja_data=0x10003000
        q(obj+0x190,ninja_data);u.mem_write(obj+0x2b6,bytes([bool(fourth_jump)]))
        for i,v in enumerate(data):f(ninja_data+0x10+i*4,v)
        u.reg_write(UC_ARM64_REG_X0,obj);u.emu_start(start,0x1001f000,count=5000)
        return struct.unpack('<f',u.mem_read(obj+0x144,4))[0]
