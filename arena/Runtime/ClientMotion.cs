// Recovered reducer behavior. Unity calls, hotfix dispatch, collision queries,
// reset/recycle and parent transforms are outside these reducers.
namespace MR3A.Arena
{
    public struct V3
    {
        public float X,Y,Z;
        public V3(float x,float y,float z=0){X=x;Y=y;Z=z;}
    }
    public struct CapsuleState
    {
        public float Radius,Height;
        public V3 Center;
        public string SetterOrder;
    }
    public sealed class CapsuleParameters
    {
        public float NormalRadius,NormalHeight,RollRadius,RollHeight,JumpHeight;
        public V3 NormalCenter,RollCenter,JumpCenter,SlideCenter;
        // Values must come from the selected prefab; no role defaults here.
    }
    public static class ClientCollider
    {
        public static CapsuleState Change(int animationState,CapsuleState current,
                                          CapsuleParameters p,bool mounted,bool capsulePresent)
        {
            current.SetterOrder="";
            if(mounted || !capsulePresent)return current;
            if(animationState==8) {
                current.Center=p.RollCenter;current.Radius=p.RollRadius;current.Height=p.RollHeight;
                current.SetterOrder="center,radius,height";
            } else if(animationState==18) {
                current.Center=p.SlideCenter;current.Radius=p.NormalRadius;current.Height=p.NormalRadius;
                current.SetterOrder="center,radius,height";
            } else {
                current.Center=animationState==3?p.JumpCenter:p.NormalCenter;
                current.Height=animationState==3?p.JumpHeight:p.NormalHeight;
                current.Radius=p.NormalRadius;current.SetterOrder="center,height,radius";
            }
            return current;
        }
    }
    public struct PlatformState
    {
        public bool Moving;
        public float Remaining,Left,Right,Bottom,Top;
        public V3 Position;
    }
    public static class ClientAirGround
    {
        // Bounds are the client's internal moving bounds, not inferred visual size.
        public static PlatformState Step(PlatformState s,float speedX,float speedY,
                                        float triggerDistance,float roleX,int direction,float fixedDeltaTime)
        {
            if(!s.Moving) {
                if(s.Remaining<=0)return s;
                if(direction>=1) {
                    if(s.Left-roleX>triggerDistance)return s;
                } else if(direction<0) {
                    if(roleX-s.Right>triggerDistance)return s;
                } else return s;
                s.Moving=true;
            }
            if(s.Remaining<=0)return s;
            s.Remaining-=fixedDeltaTime;
            float dx=speedX*fixedDeltaTime,dy=speedY*fixedDeltaTime;
            s.Position.X+=dx;s.Position.Y+=dy;
            s.Left+=dx;s.Right+=dx;s.Bottom+=dy;s.Top+=dy;
            return s;
        }
    }
    public static class ClientGravity
    {
        // data follows the 24 scalar NinjaData fields in their original order.
        // State IDs are NinjaPhysicsState, not NinjaAnimState.
        public static float Select(int state,bool inJump4,float[] data)
        {
            if(data==null || data.Length!=24)throw new System.ArgumentException("Expected 24 NinjaData fields");
            switch(state) {
                case 0:case 11:case 12:case 13:case 15:case 22:return data[6];
                case 14:case 28:case 43:case 70:return data[5];
                case 16:case 29:return data[8];
                case 17:case 20:return data[9];
                case 18:return data[inJump4?14:11];
                case 19:return data[inJump4?15:12];
                case 23:case 30:case 32:case 33:case 37:case 38:case 39:
                case 41:case 53:case 58:case 59:case 71:return data[12];
                default:return 0;
            }
        }
    }

    public struct JumpEntryState
    {
        public int PhysicsState;
        public float VelocityY;
        public bool Glided,ResetJumpTimes,InputJump2;
        public string Events;
    }
    public static class ClientJumpEntry
    {
        // Base Xiaohei fixture: no glide and no ItemShell. Caller decides whether
        // input is accepted; this mirrors EnterJump/EnterJump2, not Jump's gate.
        public static JumpEntryState Enter(bool second,JumpEntryState s,float bonus,
            float force1,float force2,bool cloned,bool water,bool sync)
        {
            s.Events="";
            if(bonus>=1)return s;
            s.PhysicsState=second?16:14;s.VelocityY=second?force2:force1;
            if(second) {
                if(!cloned)s.Events="jump_sky_smoke,audio:102";
                s.ResetJumpTimes=false;s.InputJump2=false;
            } else {
                s.Glided=false;
                if(!cloned)s.Events=water?"audio:115":"audio:101";
                if(!sync)s.Events+=(s.Events.Length==0?"":",")+"end_special_move:25";
            }
            return s;
        }
    }

    public struct FlatFlightState
    {
        public int PhysicsState;
        public V3 Position,Velocity,JumpFromPoint;
    }
    public static class ClientFlatFlight
    {
        // Restricted to the explicit flat-ground basic-jump fixture used by the
        // native oracle. No platforms, slopes, modifiers, input, clone or glide.
        public static FlatFlightState Step(FlatFlightState s,float[] data,float dt,float groundY)
        {
            if(s.PhysicsState!=14 && s.PhysicsState!=15 && s.PhysicsState!=16 && s.PhysicsState!=17)
                throw new System.ArgumentException("Only basic jump/fall states supported");
            float foot=data[1];
            bool falling=s.PhysicsState==15 || s.PhysicsState==17;
            float trigger=System.Math.Max(foot,System.Math.Abs(s.Velocity.Y)*dt+.001f);
            if(falling && s.Position.Y<groundY+trigger) {
                s.PhysicsState=5;s.Position.Y=groundY+foot;s.Velocity.Y=0;
                s.Velocity.X=data[2];
            } else {
                float acceleration=ClientGravity.Select(s.PhysicsState,false,data)*dt;
                acceleration*=3.5f;
                s.Velocity.Y=System.Math.Max(-40,s.Velocity.Y+acceleration);
                if(s.Velocity.Y<0 && s.PhysicsState==14){s.PhysicsState=15;s.JumpFromPoint=s.Position;}
                else if(s.Velocity.Y<0 && s.PhysicsState==16)s.PhysicsState=17;
            }
            s.Position.X+=s.Velocity.X*dt;s.Position.Y+=s.Velocity.Y*dt;s.Position.Z+=s.Velocity.Z*dt;
            return s;
        }
    }

}
