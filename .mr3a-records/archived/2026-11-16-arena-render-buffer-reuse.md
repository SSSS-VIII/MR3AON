# Unity读回复用托管像素缓冲区

## 现象与原因

v62两次捕获345/429ms发生在Unity接收请求或进入EOF之前，ReadPixels和传输仍快。原托管发送器虽避免XLua复制大字符串，但非泛型GetRawTextureData每次仍分配640×360×4=921600字节数组。不能仅凭时序认定大停顿由GC造成，也不关闭原游戏GC。

## 改动

内部RenderCapture的Lua发送器改为一次分配托管byte[]，逐帧读取Texture2D.GetRawTextureData<byte>()的NativeArray视图、CopyTo既有数组，再直接Stream.Write。仍通过.NET Expression解释执行Action，原始字节不穿过XLua字符串边界。byte[]在托管表达式内部创建并保留在object[]，临时NativeArray是纹理所有的视图，不Dispose、不换纹理或原游戏内存。

反射MakeGenericMethod也使用明确五参数Invoke，绕过XLua params把Type误当Type[]的问题。此前原型GetTotalMemory接口被裁剪、直接MakeGenericMethod重载失败均保留报告，不算成功。捕获对象、认证、回收、协议、原生物理及默认FastCapture入口不变；只改已有可选渲染读回实现。

## 验证

ignored证据目录为debug/arena-client/yolo/finetune/rope-recovery-v37/render-readback-probe/：

- v63c复用原型600/600同码同帧、无错误及清理残留。
- v64暂停场景顺序对照各1200帧，原路径CollectionCount(0)增加49，复用路径增加0；两组1200/1200同码同帧。请求中位16.372/16.371ms，P95 17.655/17.743ms，最大25.102/22.163ms。普通耗时并未显著变快，不把短对照推断成所有大停顿消失。
- 两组首张原图仅时间码352像素不同；抹除校准标记区域后MAE/max均0，场景像素完全一致。水印图只校准，不训练。
- v65原1101安全开头各4秒，轻负载240/240、main21/phase18/perception/MPC负载96/96均同码同帧、严格处于resume和pause之间，原渲染约60.02fps。推理前抹码、动作丢弃；恢复5000血/暂停/菜单/键盘，临时全局与对象消失。不能代表高级密集板。
- v66实际生产Lua（数组大小由纹理尺寸计算）300/300同码同帧；请求中位16.411/P95 17.149/max17.870ms，读回开始至宿主中位3.402ms；GC计数未增，清理正常。
- 捕获协议14项通过，正确YOLO Python环境全arena回归650通过/2可选依赖跳过，diff检查通过。基础Agent环境缺cv2导致一次全arena收集失败，随后在已有专用环境复验通过，未向基础环境安装包。

写码→宿主仍只是内容龄期保守上界；EOF读回开始不是曝光时间。当前只证明减少捕获分配与回收压力，未证明闭环无伤改进，下一步冻结源跑飞竹及五六关板，不晋升细时间网格。
