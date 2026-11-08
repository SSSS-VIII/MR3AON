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
        }else throw new Exception("Unknown probe input");
    }}
}
