# 当前渲染帧取图：原生读回与本地闭环实验入口

## 现象与原因

原Android captureDisplay请求约4ms，但像素码校准证明返回内容另有约25–50ms龄期，不能用服务耗时代表视觉实时性。固定回填45ms会掩盖不同缓冲/负载条件，因此继续寻找不经过桌面环境或宿主合成器的捕获路径。前序方法与边界见[内容龄期校准](2026-11-16-arena-frame-age-calibration.md)。

实际客户端为Unity2022.3.62f2c1、NinjaPipeline自定义SRP。Camera.AddCommandBuffer(AfterEverything)没有得到最终画面；被裁剪的ScreenCapture接口不能用；直接把backbuffer Blit到640×360只截取左下部分。这些失败试验均保留，没有把黑图/裁图的高速结果当成成功。全屏ReadPixels可用但传8MB过慢。最终为WaitForEndOfFrame后ExecuteCommandBuffer：CameraTarget先复制到原1920×1080 RT，再缩到640×360 RT，最后RGBA32 ReadPixels。无需Apply；暂停菜单与原Android640图逐像素比较MAE/P95/max均为0。

## 改动

新增内部可选RenderCapture，沿用FastCapture的InstanceSession控制租约、原Android按键注入和时钟校准，只替换取图。原默认入口不变，无用户菜单/新CLI选项；研究runner通过内部参数render_capture启用，setup记录来源及Python/Lua/Java三份SHA。逐帧另存渲染序号、原读回时钟和接收时间，仅用于审计，不把原位置/碰撞器/板ID或按键回执作为演员输入。paired_step明确拒绝，避免混用两种图像源。

原Lua桥只安装自身临时GameObject/EventTrigger协程、CommandBuffer和纹理；复制后恢复RenderTexture.active，停止只取消自己的handle并释放对象，不修改原相机、动作/物理/速度。游戏UID10126的IPv4/IPv6禁止联网路由保持。游戏只监听127.0.0.1并验证本次32字符token；shell UID的Java relay通过命名设备连接转发到固定loopback端口，未开放游戏外网。租约内退出清理及失败路径均保留。

GetRawTextureData经过XLua会把约921KB byte[]转换成Lua字符串，写回又复制，初版出现P95约56ms。改为一次构建.NET Expression解释执行的Action，在托管侧直接GetRawTextureData→Stream.Write，原始像素不再跨Lua字符串边界。没有加载替代游戏DLL或改变客户端机制。反射使用明确五参数Invoke，避免XLua把短重载参数误认成BindingFlags。

## 已完成验证

14项无设备CPU协议/实例限制/坏时钟/序号/尺寸测试通过，Python编译和diff检查通过。实测证据均在ignored `debug/arena-client/yolo/finetune/rope-recovery-v37/render-readback-probe/`，保留所有试验及原日志：

- `backend-managed-v19.json`：120帧请求中位约16.66ms，退出后render全局与场景对象均消失，仍暂停。
- `backend-paused-v20-managed/report.json`：300/300 nonce、CRC、像素码帧号与本次读回帧号一致。请求中位16.355/P95 17.480/max24.151ms；写码→宿主中位6.594/P95 7.561/max13.856ms；读回开始→宿主中位2.788/P95 3.687/max10.887ms。无错误，停止清理成功。
- `backend-active-v21-light`：原1101安全开头4秒、238/238严格活动帧全部同码同帧，写码→宿主中位6.284ms/max40.036ms，原渲染约59.34fps。
- `backend-active-v21-inference`：冻结main21/phase18/perception/MPC实际负载，时间码区域先抹黑、决策丢弃不发键；104/104严格活动帧全部同码同帧，写码→宿主中位5.788ms/max17.795ms，读回开始→宿主中位2.396ms，原渲染约59.98fps。推理/决策中位17.23/P95约39.91ms。仅安全1101，不能代表密集高级板最坏负载。

两个活动组均按resume.frame < code.frame < pause.frame复核，全部样本落在边界内；恢复5000血/暂停/菜单/键盘，render与marker对象/全局均消失。原报告及strict-active-review.json保留完整分布，不删除尖峰。

## 时间定义与尚未完成项

写码发生在渲染前，因此写码→宿主是内容龄期的保守上界。frame_age的EOF回调可能排在同步捕获之后，不能把两者差值当曝光时间，更不能沿用早期试验中约0.2ms的误导数字。Frame.device_captured_ns为EOF后开始读回时刻，并非曝光时间；时钟偏差每轮由原worker测量。

v53已冻结源码开始六关两板、相同种子Android与Render四回合对照；未出结果前不宣称闭环改善。首次路径是可用的研究入口，尚未晋升默认，也未实现无伤。后续优先检查实际actor渲染帧率、取图清理、受伤时刻与坡面/动作预测，不用旧有伤通过当本版无伤验收。
