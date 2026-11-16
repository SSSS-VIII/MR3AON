local X=CS.System.Linq.Expressions.Expression
local flags=CS.System.Reflection.BindingFlags.__CastFrom(60)
local function array(kind,values)
 local a=CS.System.Array.CreateInstance(kind,#values)
 for i,v in ipairs(values)do a[i-1]=v end
 return a
end
local function method(kind,name,count)
 local all=kind:GetMethods(flags)
 for i=0,all.Length-1 do local m=all[i]
  if m.Name==name and not m.IsGenericMethod and m:GetParameters().Length==count then return m end
 end
 assert(false,'Capture method absent: '..name)
end
local function make_managed_sender(texture,stream)
 local raw_method
 local methods=typeof(CS.UnityEngine.Texture2D):GetMethods(flags)
 for i=0,methods.Length-1 do local m=methods[i]
  if m.Name=='GetRawTextureData'and m.IsGenericMethod and m:GetParameters().Length==0 then
   local type_args=array(typeof(CS.System.Type),{typeof(CS.System.Byte)})
   local invoke_args=array(typeof(CS.System.Object),{type_args})
   raw_method=method(typeof(CS.System.Reflection.MethodInfo),'MakeGenericMethod',1):Invoke(m,CS.System.Reflection.BindingFlags.__CastFrom(0),nil,invoke_args,nil);break
  end
 end
 assert(raw_method,'Generic raw view absent')
 local write_method=method(typeof(CS.System.IO.Stream),'Write',3)
 local bytes=typeof(CS.System.Byte):MakeArrayType()
 local copy_method
 local copies=raw_method.ReturnType:GetMethods(flags)
 for i=0,copies.Length-1 do local m=copies[i];local ps=m:GetParameters()
  if m.Name=='CopyTo'and ps.Length==1 and ps[0].ParameterType.FullName=='System.Byte[]'then copy_method=m;break end
 end
 assert(copy_method,'Native byte view CopyTo absent')
 local function expressions(values)return array(typeof(CS.System.Linq.Expressions.Expression),values)end
 local function action(body)
  local args=array(typeof(CS.System.Object),{typeof(CS.System.Action),body,array(typeof(CS.System.Linq.Expressions.ParameterExpression),{})})
  local lambda=method(typeof(CS.System.Linq.Expressions.Expression),'Lambda',3):Invoke(nil,CS.System.Reflection.BindingFlags.__CastFrom(0),nil,args,nil)
  assert(lambda,'Lambda absent');return lambda:Compile(true)
 end
 local zero=X.Default(typeof(CS.System.Int32))
 -- Allocate byte[] inside managed code: XLua otherwise converts it to a Lua string.
 local holder=CS.System.Array.CreateInstance(typeof(CS.System.Object),1)
 local slot=X.ArrayAccess(X.Constant(holder),expressions({zero}))
 local count=X.Convert(X.Constant(texture.width*texture.height*4),typeof(CS.System.Int32))
 local buffer_new=X.NewArrayBounds(typeof(CS.System.Byte),expressions({count}))
 local allocation=X.Assign(slot,X.Convert(buffer_new,typeof(CS.System.Object)))
 local allocate=action(X.Block(array(typeof(CS.System.Linq.Expressions.ParameterExpression),{}),expressions({allocation,X.Default(write_method.ReturnType)})))
 allocate()
 local buffer=X.Convert(slot,bytes)
 local raw=X.Variable(raw_method.ReturnType,'raw')
 local assign=X.Assign(raw,X.Call(X.Constant(texture),raw_method,expressions({})))
 local copy=X.Call(raw,copy_method,expressions({buffer}))
 local write=X.Call(X.Constant(stream),write_method,expressions({buffer,zero,X.ArrayLength(buffer)}))
 local body=X.Block(array(typeof(CS.System.Linq.Expressions.ParameterExpression),{raw}),expressions({assign,copy,write}))
 MR3A.renderCapture.result.sender='native_byte_view_reused_managed_buffer'
 return action(body)
end

-- Copy the final rendered image; no input, physics or original camera changes.
local E,U=MR3A,CS.UnityEngine
local W=CS.System.Diagnostics.Stopwatch
local function now()return W.GetTimestamp()/W.Frequency end
assert(not E.renderCapture,'Previous render capture remains')
assert(U.Time.timeScale==0 and not E.busy,'Initialize render capture while paused')
local p={result={active=true,frames={},started=now()},token=TOKEN,width=640,height=360}
E.renderCapture=p
local function cleanup()
 p.result.active=false;p.sender=nil
 if p.command then p.command:Release();p.command=nil end
 if p.full then p.full:Release();U.Object.Destroy(p.full);p.full=nil end
 if p.target then p.target:Release();U.Object.Destroy(p.target);p.target=nil end
 if p.texture then U.Object.Destroy(p.texture);p.texture=nil end
 if p.client then p.client:Close();p.client=nil end
 if p.listener then p.listener:Close();p.listener=nil end
 if p.root then U.Object.Destroy(p.root);p.root=nil end
 p.result.stopped=now()
end
function E.render_capture_stop()
 if p.root and p.runner and p.coroutine then p.runner:StopCoroutine(p.coroutine);p.coroutine=nil end
 cleanup();return p.result
end
function E.render_capture_uninstall()
 E.render_capture_stop();E.renderCapture=nil
 E.render_capture_stop=nil;E.render_capture_uninstall=nil
 return true
end
local ok,err=pcall(function()
 p.target=U.RenderTexture(640,360,0,U.RenderTextureFormat.ARGB32);p.target:Create()
 p.full=U.RenderTexture(U.Screen.width,U.Screen.height,0,U.RenderTextureFormat.ARGB32);p.full:Create()
 p.command=U.Rendering.CommandBuffer();p.command.name='MR3A_RenderCaptureCopy'
 p.command:Blit(U.Rendering.RenderTargetIdentifier(U.Rendering.BuiltinRenderTextureType.CameraTarget),U.Rendering.RenderTargetIdentifier(p.full))
 p.command:Blit(U.Rendering.RenderTargetIdentifier(p.full),U.Rendering.RenderTargetIdentifier(p.target))
 p.texture=U.Texture2D(p.width,p.height,U.TextureFormat.RGBA32,false)

 p.listener=CS.System.Net.Sockets.Socket(CS.System.Net.Sockets.AddressFamily.InterNetwork,CS.System.Net.Sockets.SocketType.Stream,CS.System.Net.Sockets.ProtocolType.Tcp);assert(p.listener,"Socket unavailable");p.listener:Bind(CS.System.Net.IPEndPoint(CS.System.Net.IPAddress.Loopback,0));p.listener:Listen(1)
 p.result.port=p.listener.LocalEndPoint.Port
 p.root=U.GameObject('MR3A_RenderCapture');U.Object.DontDestroyOnLoad(p.root)
 p.runner=p.root:AddComponent(typeof(U.EventSystems.EventTrigger))
 p.coroutine=p.runner:StartCoroutine(require('common/util').cs_generator(function()
  local good,error=pcall(function()
   local eof=U.WaitForEndOfFrame();local sequence=0
   while p.result.active and now()-(p.last_request or p.result.started)<10 do
    coroutine.yield(nil)
    if not p.client and p.listener:Poll(0,CS.System.Net.Sockets.SelectMode.SelectRead)then
     p.client=p.listener:Accept();p.client.NoDelay=true
     p.stream=CS.System.Net.Sockets.NetworkStream(p.client,false);p.stream.ReadTimeout=1000;p.stream.WriteTimeout=1000;p.sender=make_managed_sender(p.texture,p.stream)
    end
    if p.stream and p.client:Poll(0,CS.System.Net.Sockets.SelectMode.SelectRead)then
     if not p.authenticated then
      local token=''
      for i=1,#p.token do local b=p.stream:ReadByte();assert(b>=0,'Auth EOF');token=token..string.char(b)end
      assert(token==p.token,'Auth mismatch');p.authenticated=true
     end
     if p.client:Poll(0,CS.System.Net.Sockets.SelectMode.SelectRead)then
      local command=p.stream:ReadByte()
      if command<=0 then break end
      assert(command==1,'Unknown capture command')
      local requested=now();p.last_request=requested;coroutine.yield(eof)
      local frame=U.Time.frameCount;local stamp=now();local previous=U.RenderTexture.active
      local read_ok,read_error=pcall(function()
       U.RenderTexture.active=nil;U.Graphics.ExecuteCommandBuffer(p.command)
       U.RenderTexture.active=p.target;p.texture:ReadPixels(U.Rect(0,0,p.width,p.height),0,0)
      end)
      U.RenderTexture.active=previous;assert(read_ok,tostring(read_error))
      local read_end=now();local ready=read_end;local size=p.width*p.height*4
      sequence=sequence+1
      local header=string.format('{"sequence":%d,"frame":%d,"size":%d,"requested":%.9f,"eof":%.9f,"read_end":%.9f,"ready":%.9f}\n',sequence,frame,size,requested,stamp,read_end,ready)
      p.stream:Write(header,0,#header);p.sender()
      if #p.result.frames>=32 then table.remove(p.result.frames,1)end
      p.result.count=sequence
      p.result.frames[#p.result.frames+1]={sequence=sequence,frame=frame,eof=stamp,read_end=read_end,ready=ready,send_end=now(),same_frame=U.Time.frameCount==frame}
     end
    end
   end
  end)
  if not good then p.result.error=tostring(error)end
  cleanup()
 end))
end)
if not ok then p.result.error=tostring(err);cleanup();assert(false,tostring(err))end
return {port=p.result.port,source='backbuffer_full_then_scaled_blit',width=p.width,height=p.height}
