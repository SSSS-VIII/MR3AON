#!/usr/bin/env python3
"""Compare compiled C# reducers with actual client ARM64 instructions offline."""
import argparse
import json
from pathlib import Path
import random
import struct
import subprocess
import tempfile
from arena_native_oracle import NativeOracle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--editor',type=Path,required=True,help='Installed Unity Editor directory')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    mono=args.editor/'Data/MonoBleedingEdge/bin/mono'
    compiler=args.editor/'Data/MonoBleedingEdge/lib/mono/4.5/mcs.exe'
    oracle=NativeOracle(args.library)
    commands=[];expected=[];details=[]
    def collider(state,mounted,present,radius,height):
        commands.append(f'C {state} {int(mounted)} {int(present)} {radius} {height}')
        e=oracle.collider(state,mounted=mounted,capsule_present=present,radius=radius,height=height)
        expected.append([e['radius'],e['height'],*e['center'],','.join(e['calls']) or '-'])
        details.append({'kind':'collider','state':state,'mounted':mounted,'present':present})
    for state in range(55):
        for mounted,present in [(False,True),(True,True),(False,False),(True,False)]:collider(state,mounted,present,.1,1.8)
    def platform(k):
        e=oracle.platform(**k)
        vals=[int(k['moving']),k['remaining'],k['speed_x'],k['speed_y'],k['trigger_distance'],
              *k['bounds'],*k['position'],k['role_x'],k['direction'],k['fixed_dt']]
        commands.append('P '+' '.join(map(str,vals)))
        expected.append([int(e['moving']),e['remaining'],*e['bounds'],*e['position']]);details.append({'kind':'platform',**k})
    base=dict(moving=False,remaining=1,speed_x=5,speed_y=-2,trigger_distance=3,
              bounds=(10,14,2,4),position=(12,3,0),role_x=7,direction=1,fixed_dt=.02)
    for direction,xs in [(1,[6.999,7,7.001]),(-1,[16.999,17,17.001]),(0,[0,7,20])]:
        for x in xs:platform({**base,'direction':direction,'role_x':x})
    for remaining in [-1,0,.001,.02,.021]:
        for moving in [True,False]:platform({**base,'moving':moving,'remaining':remaining})
    rng=random.Random(1248)
    for i in range(300):
        left=rng.uniform(-50,50);right=left+rng.uniform(.01,20)
        platform({**base,'bounds':(left,right,-3,2),'position':(left,0,.5),
                  'moving':rng.choice([True,False]),'remaining':rng.uniform(-.1,3),
                  'speed_x':rng.uniform(-20,20),'speed_y':rng.uniform(-10,10),
                  'trigger_distance':rng.uniform(-2,20),'role_x':rng.uniform(-60,60),
                  'direction':rng.choice([-2,-1,0,1,2]),'fixed_dt':rng.choice([.01,.02,1/60])})
    platform_cases=len(expected)-220
    for sample in range(3):
        data=[rng.uniform(-40,40) for _ in range(24)]
        for state in list(range(75))+[-1,75,1000]:
            for fourth in [False,True]:
                commands.append('G '+' '.join(map(str,[state,int(fourth),*data])))
                expected.append([oracle.gravity(state,fourth_jump=fourth,data=data)])
                details.append({'kind':'gravity','physics_state':state,'inJump4':fourth})
    gravity_cases=len(expected)-220-platform_cases
    for second in [False,True]:
        for bonus in [-.1,0,.999,1,1.1]:
            for cloned in [False,True]:
                for water in [False,True]:
                    for sync in [False,True]:
                        k=dict(bonus=bonus,force1=rng.uniform(15,35),force2=rng.uniform(8,16),state=5,velocity_y=rng.uniform(-10,10),
                               cloned=cloned,water=water,sync=sync,glided=rng.choice([True,False]),reset_jump_times=rng.choice([True,False]),input_jump2=rng.choice([True,False]))
                        e=oracle.jump_entry(second,**k)
                        vals=[int(second),bonus,k['force1'],k['force2'],k['state'],k['velocity_y'],
                              int(cloned),int(water),int(sync),int(k['glided']),int(k['reset_jump_times']),int(k['input_jump2'])]
                        commands.append('J '+' '.join(map(str,vals)))
                        expected.append([e['state'],e['velocity_y'],int(e['glided']),int(e['reset_jump_times']),int(e['input_jump2']),','.join(e['events']) or '-'])
                        details.append({'kind':'jump_entry','second':second,**k})
    jump_entry_cases=len(expected)-220-platform_cases-gravity_cases
    from arena_flight_oracle import flat_flight
    # Distinct up/down gravity and different fixed timesteps/ground elevations.
    base_data=[1,.75,8,-19.8,23.5,-25,-9,12.5,-9.8,-9.8,12,-9.8,-9.8,8.5,-9.8,-9.8,5,8,28,.8,5,2.5,-2,1]
    for dt in [.01,.02,1/60]:
        for second in [False,True]:
            data=list(base_data);data[2]=rng.choice([8,12,16]);ground_y=rng.choice([0,2,-3])
            pos=(5,ground_y+.75,0);vel=(data[2],data[7] if second else data[4],0);state=16 if second else 14
            trajectory=flat_flight(oracle,data,position=pos,velocity=vel,initial_state=state,fixed_dt=dt,ground_y=ground_y)
            for frame in trajectory['frames']:
                commands.append('F '+' '.join(map(str,[state,*pos,*vel,dt,ground_y,*data])))
                expected.append([frame['state'],*frame['position'],*frame['velocity']])
                details.append({'kind':'flat_flight','frame':frame['frame'],'dt':dt,'second':second})
                state=frame['state'];pos=frame['position'];vel=frame['velocity']
    flight_frames=len(expected)-220-platform_cases-gravity_cases-jump_entry_cases
    def query(bounds,x,y,direction,excluded):
        commands.append('Q '+' '.join(map(str,[x,y,direction,excluded,len(bounds),*[v for b in bounds for v in b]])))
        expected.append([oracle.query_platform(bounds,x=x,y=y,direction=direction,excluded=excluded)])
        details.append({'kind':'platform_query','bounds':bounds,'x':x,'y':y,'direction':direction,'excluded':excluded})
    fixed_bounds=[(0,10,2,1),(0,10,4,3),(0,10,4,2)]
    for x in [-.001,0,5,10,10.001]:
        for y in [1.999,2,3.999,4,4.001]:
            for excluded in [-1,0,1,2]:query(fixed_bounds,x,y,1,excluded)
    for i in range(300):
        direction=rng.choice([-2,-1,0,1,2]);bounds=[]
        for j in range(rng.randrange(9)):
            a=rng.uniform(-10,10);b=a+rng.uniform(.01,10)
            if direction<0:a,b=b,a
            top=rng.uniform(-5,8);bounds.append((a,b,top,top-1))
        query(bounds,rng.uniform(-12,12),rng.uniform(-6,10),direction,rng.randrange(-1,len(bounds)+1))
    platform_query_cases=len(expected)-220-platform_cases-gravity_cases-jump_entry_cases-flight_frames
    group_tests=[([[(0,10,4,2)],[(0,10,4,2)],[(0,10,4,2)]],5,5,1,-1),([[],[],[]],0,0,1,-1)]
    for i in range(150):
        groups=[];direction=rng.choice([-1,0,1])
        for g in range(3):
            group=[]
            for j in range(rng.randrange(6)):
                a=rng.uniform(-10,10);b=a+rng.uniform(.1,12)
                if direction<0:a,b=b,a
                group.append((a,b,rng.choice([0,2,4,6]),-1))
            groups.append(group)
        group_tests.append((groups,rng.uniform(-10,10),rng.choice([0,2,4,6]),direction,rng.randrange(-1,sum(map(len,groups))+1)))
    for groups,x,y,direction,excluded in group_tests:
        flat=[v for g in groups for b in g for v in b]
        commands.append('T '+' '.join(map(str,[x,y,direction,excluded,*map(len,groups),*flat])))
        expected.append([oracle.query_three_platform_groups(groups,x=x,y=y,direction=direction,excluded=excluded)])
        details.append({'kind':'three_platform_groups','groups':groups,'x':x,'y':y,'direction':direction,'excluded':excluded})
    with tempfile.TemporaryDirectory(prefix='arena-motion-') as folder:
        exe=Path(folder)/'MotionProbe.exe'
        subprocess.run([str(mono),str(compiler),'-out:'+str(exe),str(root/'arena/Runtime/ClientMotion.cs'),str(root/'arena/Validation/MotionProbe.cs')],check=True)
        run=subprocess.run([str(mono),str(exe)],input='\n'.join(commands)+'\n',text=True,capture_output=True,check=True)
    actual=run.stdout.splitlines();assert len(actual)==len(expected)
    failures=[]
    for i,(line,want) in enumerate(zip(actual,expected)):
        got=line.split()[1:]
        matches=len(got)==len(want)
        for a,b in zip(got,want):
            matches=matches and (a==b if isinstance(b,str) else struct.pack('<f',float(a))==struct.pack('<f',b))
        if not matches:failures.append({'input':commands[i],'actual':got,'expected':want,'context':details[i]})
    report={'status':'reducer_native_equivalence_only_not_game_equivalence','cases':len(expected),
            'collider_cases':220,'platform_cases':platform_cases,'gravity_cases':gravity_cases,'jump_entry_cases':jump_entry_cases,'flight_frames':flight_frames,'platform_query_cases':platform_query_cases,'group_query_cases':len(expected)-220-platform_cases-gravity_cases-jump_entry_cases-flight_frames-platform_query_cases,'failures':failures,
            'scope':'Unity calls/context are fixtures; no PhysX, hotfix, reset, prefab layout or rendering validation'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'cases':len(expected),'failures':len(failures)}))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
