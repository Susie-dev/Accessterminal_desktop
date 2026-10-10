# 更新日志 — Accessterminal_desktop（室内机）

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。
协议不兼容变更必须递增 `protocol.h` 中的 `kProtocolVersion`。

## [1.0.0] — 重构版

### 架构

- 将 718 行的 `widget.cpp` 与 575 行的 `form_phonecall.cpp` 按职责拆分：
  - `core/net/SignalingServer` —— TCP 信令服务端
  - `core/net/MonitorClient` —— UDP 50000 远程监看
  - `core/media/CallSession` —— UDP 12345 音频 + 23456 视频
  - `core/weather/WeatherService` —— 天气请求与解析
  - `hal/SerialLight` —— 灯控串口
- 从门口机仓库同步 `core/net/protocol.h`（SHA256 一致），
  由单元测试与 `tools/check_protocol_sync.py` 守护两端一致性。
- 引入 `AppConfig` 三级配置，消除硬编码 IP、端口、串口名、
  天气接口与灯控指令。
- 新增 CMake 构建，重写 `.pro` 适配新目录结构。

### 修复

- **TCP 粘包/半包漏判信令**：原实现用 `data.trimmed()` 与 `"call"` 整体比较，
  一次 `readAll` 含多条或不足一条信令时会漏判。改为按 `\n` 切分后逐条解析。
- **回执悬垂指针**：`accepted` / `hangupClicked` 的 lambda 直接捕获裸
  `QTcpSocket*`，连接在通话期间断开时回执会访问已析构对象。
  改用 `QPointer` 守护。
- **浮层窗口泄漏**：通话浮层为无父顶层窗口，`Widget` 析构时未关闭，
  会残留窗口与音频设备句柄。现于析构中显式关闭。
- **门铃音循环**：`QMediaPlayer::stateChanged` 原用旧式
  `SIGNAL`/`SLOT` 字符串连接，槽签名与 Qt5.15 的 `State` 枚举不一致。
  改为 lambda。
- **天气解析越界**：`forecast` 数组为空时原代码直接访问 `[0]`。已加校验。
- **监看动画标志**：`firstShow` 在开启/关闭两条分支都被覆盖，
  停止监看后未重置，导致再次开启时动画不播放。现统一重置。
- **串口名**：原硬编码 Windows 的 `COM24`，在 Linux 目标上必然打不开。
  改为可配置的 `/dev/ttyUSB0`。

### 兼容性

- 界面布局、`.ui` 文件、样式表、动画时长与文案**均未改动**。
- 圆角半径、黑屏/还原逻辑、离线时不响铃、远程监看的
  `getframe`/`stop` 语义与每包一帧完整 JPEG 均未改动。

### 已知限制

- 界面按 1100×650 触摸屏设计，未做自适应布局。
- 天气接口为第三方免费服务，不可用时不影响通话功能。
