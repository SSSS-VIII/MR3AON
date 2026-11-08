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

}
