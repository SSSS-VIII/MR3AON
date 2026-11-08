using System;
using System.Globalization;
using MR3A.Arena;
class MotionProbe
{
    static float F(string v){return float.Parse(v,CultureInfo.InvariantCulture);}
    static string R(float v){return v.ToString("R",CultureInfo.InvariantCulture);}
    static void Main(){string line;while((line=Console.ReadLine())!=null){
        var v=line.Split(' ');
        if(v[0]=="C"){
            var p=new CapsuleParameters{NormalRadius=.2f,NormalHeight=1.8f,RollRadius=.1f,RollHeight=.1f,JumpHeight=1.2f,
                NormalCenter=new V3(.1f,0),JumpCenter=new V3(.1f,.3f),RollCenter=new V3(.05f,0),SlideCenter=new V3(.05f,-.3f)};
            var s=ClientCollider.Change(int.Parse(v[1]),new CapsuleState{Radius=F(v[4]),Height=F(v[5]),Center=new V3(.1f,0)},p,v[2]=="1",v[3]=="1");
            Console.WriteLine(string.Join(" ",new[]{"C",R(s.Radius),R(s.Height),R(s.Center.X),R(s.Center.Y),R(s.Center.Z),s.SetterOrder.Length==0?"-":s.SetterOrder}));
        }else if(v[0]=="P"){
            var s=new PlatformState{Moving=v[1]=="1",Remaining=F(v[2]),Left=F(v[6]),Right=F(v[7]),Bottom=F(v[8]),Top=F(v[9]),Position=new V3(F(v[10]),F(v[11]),F(v[12]))};
            s=ClientAirGround.Step(s,F(v[3]),F(v[4]),F(v[5]),F(v[13]),int.Parse(v[14]),F(v[15]));
            Console.WriteLine(string.Join(" ",new[]{"P",s.Moving?"1":"0",R(s.Remaining),R(s.Left),R(s.Right),R(s.Bottom),R(s.Top),R(s.Position.X),R(s.Position.Y),R(s.Position.Z)}));
        }else if(v[0]=="G"){
            var data=new float[24];for(int i=0;i<24;i++)data[i]=F(v[i+3]);
            Console.WriteLine("G "+R(ClientGravity.Select(int.Parse(v[1]),v[2]=="1",data)));
        }else if(v[0]=="J"){
            var s=new JumpEntryState{PhysicsState=int.Parse(v[5]),VelocityY=F(v[6]),Glided=v[10]=="1",ResetJumpTimes=v[11]=="1",InputJump2=v[12]=="1"};
            s=ClientJumpEntry.Enter(v[1]=="1",s,F(v[2]),F(v[3]),F(v[4]),v[7]=="1",v[8]=="1",v[9]=="1");
            Console.WriteLine(string.Join(" ",new[]{"J",s.PhysicsState.ToString(),R(s.VelocityY),s.Glided?"1":"0",s.ResetJumpTimes?"1":"0",s.InputJump2?"1":"0",s.Events.Length==0?"-":s.Events}));
        }else if(v[0]=="F"){
            var s=new FlatFlightState{PhysicsState=int.Parse(v[1]),Position=new V3(F(v[2]),F(v[3]),F(v[4])),Velocity=new V3(F(v[5]),F(v[6]),F(v[7]))};
            var data=new float[24];for(int i=0;i<24;i++)data[i]=F(v[i+10]);
            s=ClientFlatFlight.Step(s,data,F(v[8]),F(v[9]));
            Console.WriteLine(string.Join(" ",new[]{"F",s.PhysicsState.ToString(),R(s.Position.X),R(s.Position.Y),R(s.Position.Z),R(s.Velocity.X),R(s.Velocity.Y),R(s.Velocity.Z)}));
        }else if(v[0]=="Q"){
            int n=int.Parse(v[5]);var bounds=new AirPlatformBounds[n];
            for(int i=0;i<n;i++)bounds[i]=new AirPlatformBounds{StartX=F(v[6+i*4]),EndX=F(v[7+i*4]),TopY=F(v[8+i*4]),BottomY=F(v[9+i*4])};
            Console.WriteLine("Q "+ClientPlatformQuery.Select(bounds,F(v[1]),F(v[2]),int.Parse(v[3]),int.Parse(v[4])));
        }else if(v[0]=="T"){
            var groups=new AirPlatformBounds[3][];int cursor=8;
            for(int g=0;g<3;g++){
                int n=int.Parse(v[5+g]);groups[g]=new AirPlatformBounds[n];
                for(int i=0;i<n;i++){groups[g][i]=new AirPlatformBounds{StartX=F(v[cursor]),EndX=F(v[cursor+1]),TopY=F(v[cursor+2]),BottomY=F(v[cursor+3])};cursor+=4;}
            }
            Console.WriteLine("T "+ClientPlatformQuery.SelectThree(groups,F(v[1]),F(v[2]),int.Parse(v[3]),int.Parse(v[4])));
        }else if(v[0]=="H"){
            var groups=new AirPlatformBounds[3][];int cursor=9;
            for(int g=0;g<3;g++){
                int n=int.Parse(v[6+g]);groups[g]=new AirPlatformBounds[n];
                for(int i=0;i<n;i++){groups[g][i]=new AirPlatformBounds{StartX=F(v[cursor]),EndX=F(v[cursor+1]),TopY=F(v[cursor+2]),BottomY=F(v[cursor+3])};cursor+=4;}
            }
            int platform;float h=ClientPlatformQuery.GroundHeight(groups,F(v[1]),F(v[2]),int.Parse(v[3]),int.Parse(v[4]),F(v[5]),out platform);
            Console.WriteLine("H "+platform+" "+R(h));
        }else throw new Exception("Unknown probe input");
    }}
}
