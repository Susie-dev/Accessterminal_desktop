# Accessterminal_desktop — 室内机

别墅门禁可视化对讲系统的**室内机（对讲主机 / 控制面板）**。
1100×650 无边框圆角控制面板，含来电浮层、远程监看、灯光控制与天气显示。

与门口机仓库 [Accessterminal_T113](../Accessterminal_T113) 通过
TCP 信令 + UDP 音视频协同工作。

---

## 功能

| 功能 | 实现 |
|------|------|
| 来电接听 | TCP 8887 监听，收到 `call` 弹出滑条接听浮层 |
| 双向语音 | UDP 12345，裸 PCM（S16_LE / 16000Hz / 单声道） |
| 视频通话 | UDP 23456，接收门口机推送的 JPEG 帧 |
| 远程开锁 | 广播 `unlock` 给所有在线门口机 |
| 远程监看 | UDP 50000，发 `getframe` / `stop` 控制门口机推帧 |
| 灯光控制 | 串口发送固定十六进制指令（4 路灯） |
| 天气显示 | HTTP 接口获取并按固定文案格式展示 |
| 屏幕开关 | 黑屏 / 还原背景 |
| 离线状态 | 渐显离线提示层；离线时不响铃 |

---

## 目录结构

```
src/
  main.cpp              程序入口
  config/               AppConfig：内置默认值 → JSON → 环境变量
  core/
    net/                protocol.h（协议唯一事实来源）、SignalingServer、MonitorClient
    media/              CallSession：双向音频 + 单向视频
    weather/            WeatherService
  hal/                  SerialLight：灯控串口
  ui/                   主窗口、通话浮层、流光引导控件
  resources/            qrc、图片、门铃音
config/appconfig.json   运行时配置
deploy/                 部署脚本、udev 规则
tests/                  协议契约单元测试
tools/                  静态校验脚本
```

---

## 构建

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j
./build/bin/smartserver
```

一键脚本（配置 + 编译 + 跑测试）：

```sh
bash tools/build_host.sh
```

产物在 `build-host/bin/smartserver`。

### 依赖

- Qt5：`Core Gui Widgets Network Multimedia SerialPort`（≥ 5.12）
- 编译期 C++11

Debian / Ubuntu：

```sh
sudo apt install qtbase5-dev qtmultimedia5-dev libqt5serialport5-dev cmake g++
```

Windows（MSYS2 + MinGW-w64）：

```sh
pacman -S mingw-w64-x86_64-gcc mingw-w64-x86_64-cmake mingw-w64-x86_64-ninja \
          mingw-w64-x86_64-qt5-base mingw-w64-x86_64-qt5-multimedia \
          mingw-w64-x86_64-qt5-serialport mingw-w64-x86_64-qt5-tools
```

### 单元测试

作为主工程的一部分构建：

```sh
cmake -S . -B build -DACCESSTERMINAL_BUILD_TESTS=ON
cmake --build build && ctest --test-dir build --output-on-failure
```

也可以**独立构建**（不依赖主工程，不需要硬件相关依赖）：

```sh
cmake -S tests -B /tmp/desktop-tests -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/desktop-tests
ctest --test-dir /tmp/desktop-tests --output-on-failure
```

当前 3 个目标：`desktop_protocol`（协议编解码）、`desktop_app_config`
（配置与灯控指令解析）、`desktop_signaling_server`（TCP 8887 信令服务端，
真实 socket 端到端）。

> `tests/CMakeLists.txt` 此前缺 `cmake_minimum_required`/`project()`，独立构建
> 会直接配置失败；补上之后又会因为缺 `enable_testing()` 而"构建成功、
> `ctest` 一个用例都不跑"。这类失败**只看构建退出码会被误判为通过**。现由
> `check_subproject_cmake_is_selfcontained` 强制，自检见
> `tools/verify_subcmake.py`（8/8 用例）。与门口机侧对称修复。

### 已验证的构建环境

本工程已做过真实的完整构建（编译 + 链接 + 单元测试通过）：

| 项目 | 版本 |
| --- | --- |
| 编译器 | MinGW-w64 GCC 16.2.0 |
| CMake | 4.4.4 |
| Qt | 5.15.19 |
| 平台 | Windows 10 + MSYS2 |

结果：0 error、0 warning，`ctest` 1/1 通过。

也保留了 qmake 工作流（Qt Creator 可直接打开 `smartserver.pro`）：

```sh
qmake && make -j$(nproc)
```

---

## 部署

```sh
sudo ./deploy/install.sh
```

安装到 `/opt/smartserver`，配置到 `/etc/accessterminal/appconfig.json`。
自定义前缀：`PREFIX=$HOME/smartserver ./deploy/install.sh`

### 设备权限

灯控串口需要写权限；程序不再硬编码 Windows 的 `COM24`：

```sh
sudo cp deploy/99-accessterminal.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## 配置

所有参数集中在 `config/appconfig.json`，优先级为
**内置默认值 → JSON 文件 → 环境变量**。

```json
{
  "network":  { "self_ip": "192.168.1.4",
                "device_ip": "192.168.1.8",
                "signaling_port": 8887 },
  "hardware": { "serial_port": "/dev/ttyUSB0" },
  "weather":  { "url": "http://t.weather.itboy.net/api/weather/city/101230101" },
  "media":    { "ringtone": "qrc:/door.mp3", "ringtone_volume": 100 },
  "lights":   { "desk": "FD034C12045DDF", "work": "FD034C12025DDF",
                "work_round": "FD039736F44FDF", "desk_round": "FD039736F250DF",
                "wall": "FD039736F150DF" }
}
```

配置文件查找顺序：

1. 命令行第一个参数
2. 可执行文件同目录的 `appconfig.json`
3. 当前工作目录的 `config/appconfig.json`
4. `/etc/accessterminal/appconfig.json`

### 环境变量覆盖

兼容历史变量名：`SMARTSERVER_SELF_IP`、`SMARTSERVER_DEVICE_IP`

统一前缀（推荐）：

| 变量 | 含义 |
|------|------|
| `ACCESSTERMINAL_NETWORK_SELF_IP` | 本机地址 |
| `ACCESSTERMINAL_NETWORK_DEVICE_IP` | 门口机地址 |
| `ACCESSTERMINAL_NETWORK_SIGNALING_PORT` | 信令端口 |
| `ACCESSTERMINAL_HARDWARE_SERIAL_PORT` | 灯控串口 |
| `ACCESSTERMINAL_WEATHER_URL` | 天气接口（留空禁用） |

> **迁移提示**：原实现硬编码串口 `COM24`（Windows 命名），在 Linux 上
> 必然打不开。现默认值改为 `/dev/ttyUSB0`，请按实际设备在配置中调整。

---

## 通信协议

协议契约定义在 `src/core/net/protocol.h`，与门口机仓库**内容完全一致**
（SHA256 相同），由 `tests/test_protocol.cpp` 与
`tools/check_protocol_sync.py` 共同守护。

| 通道 | 端口 | 格式 |
|------|------|------|
| 信令 | TCP 8887 | UTF-8 文本行，`\n` 结束 |
| 音频 | UDP 12345 | 裸 PCM，S16_LE / 16000Hz / 单声道，320 帧（640 字节）一包 |
| 视频 | UDP 23456 | 每包一帧完整 JPEG，不重组不重传 |
| 远程监看 | UDP 50000 | 本机发 `getframe` / `stop` |

信令一览：

| 信令 | 方向 | 含义 |
|------|------|------|
| `call` | 门口机 → 室内机 | 请求呼叫 |
| `accept` | 室内机 → 门口机 | 接通，门口机据此创建音视频线程 |
| `recstop` | 室内机 → 门口机 | 挂断 |
| `unlock` | 双向 | 远程开锁（本机广播给所有在线门口机） |
| `stopsend` | 门口机 → 室内机 | 对端停止发送 |
| `getframe` | 室内机 → 门口机 | 开始推帧 |
| `stop` | 室内机 → 门口机 | 停止推帧 |

### 信令服务端（SignalingServer / TCP 8887）的行为断言

TCP 8887 是本项目**第一条协议硬约束**，但室内机侧的 `SignalingServer`
（接收门口机的 `call`/`stopsend`/`unlock`，并回 `accept`/`recstop`/`unlock`）
此前**没有任何单元测试**：只有协议编解码被 `test_protocol.cpp` 覆盖，服务端
自己的行为（接入/断开、按连接分流的解码器、回执、广播、停止）全无覆盖。

测试方式是**真实 `QTcpSocket` 连到真实 `QTcpServer`**，走完整事件循环：
bind、`newConnection`、`readyRead` 派发、`disconnected` 清理一并被验证，
而不是直接调私有槽（那会绕开真正的线上路径）。不需要任何硬件。

| 用例 | 钉住的行为 |
| --- | --- |
| `listenIsIdempotent` | 重复 `listen()` 幂等，不重复绑定 |
| `listenOnBusyPortFailsAndEmits` | 端口被占用时返回 false 并发 `errorOccurred` |
| `stopClosesListener` | `stop()` 后不再监听 |
| `clientConnect/DisconnectEmitsSignal` | 接入/断开各自发信号 |
| `receivesExactWireBytes` | `call`/`unlock`/`stopsend` 逐字节还原成枚举 |
| `multipleSignalsInOneWriteAreAllDecoded` | 一次 write 含多条信令（粘包）必须全部解出 |
| `splitSignalIsReassembled` | 被 TCP 拆成两包的信令必须拼出（半包不得丢） |
| `stopsendSplitAtAmbiguousPrefixIsNotMisdecoded` | `"stop"`+`"send\n"` **不得**被误判为 `stop` |
| `bareStopIsDecodedAsStop` | 裸 `stop\n`（远程监看停止）能立即定论 |
| `legacyRecstopWithoutNewlineIsAccepted` | 裸 `recstop`（**无 `\n`**）仍被识别（baseline 宽容语义） |
| `unknownTextIsIgnored` / `emptyLineIsIgnored` | 无法识别的文本/空行被忽略，之后仍正常 |
| `whitespaceIsTrimmed` | 前后空白被 trim 后识别 |
| `replyWritesExactWireBytes` | 回执逐字节为 `accept\n`/`recstop\n`/`unlock\n` |
| `replyRejectsInvalidSocket` / `replyRejectsUnknownSignal` | 空指针、未连接、未知信令均被拒绝 |
| `broadcastReachesAllClients` | 广播到全部已连接客户端并返回条数 |
| `broadcastRejectsUnknownSignal` / `broadcastWithNoClientsReturnsZero` | 未知信令发 0 字节；无客户端返回 0 |
| `decodersArePerConnection` | 两条连接的半包**不得串味**（解码器按 socket 分开） |
| `decoderIsClearedOnDisconnect` | 断开后清解码器（**不具区分度**，见下） |
| `disconnectOfOneClientDoesNotAffectOther` | 一条断开不影响另一条 |
| `protocolConstantsAreFrozen` | 8887、`\n`、七条信令的字节形态、`Unknown` 产生**空帧** |
| `allPortsAreDistinct` | 8887/12345/23456/50000 四个端口互不重复 |

> `QSignalSpy` 断言自定义类型前**必须** `qRegisterMetaType`：
> `Q_DECLARE_METATYPE` 只保证编译通过，跨队列投递还需运行时注册，否则参数被
> 丢成默认值（`Unknown` / `nullptr`），断言失败的样子**像被测代码的 bug**。
> 实测：只去掉 `Signal` 注册 → 只有 `receivesExactWireBytes` 失败；只去掉
> `QTcpSocket*` 注册 → 只有 `replyWritesExactWireBytes` 失败。现由
> `check_signalspy_types_are_registered` 强制，自检见
> `tools/verify_signalspy_metatype.py`（4/4）。

#### 对照实验：8 个变异体，7 个被抓，1 个如实记录

变异体都是"看起来合理但错误"的实现改动。结果：

| 变异 | 结果 |
| --- | --- |
| M1 回执用 `toWire` 而非 `frame`（漏 `\n`） | 被抓 |
| M2 `broadcast` 不校验 `Unknown`（照发空帧） | 被抓 |
| M3 `stop()` 不关闭监听 | 被抓 |
| M4 所有连接共用**一个**解码器 | 被抓（**首版测试抓不到**，见下） |
| M5 断开时不清解码器 | **仍通过** —— 只泄漏不损坏，见下 |
| M6 断开时不发 `clientDisconnected` | 被抓 |
| M7 接入时不发 `clientConnected` | 被抓 |
| M8 `listen` 失败时不发 `errorOccurred` | 被抓 |

**M4 暴露了首版测试的空转断言。** `decodersArePerConnection` 首版只断言
"最终出现了一条 `Call`"——而共用解码器**恰好也能产生一条** `Call`
（A 的前半 + B 的后半拼起来）。测试于是照样通过。真正的断言必须是
**"在错误的那一侧发生之前，什么都还没出现"**：在 A 补上自己后半**之前**
断言 `spy.count() == 0`。补上后 M4 立刻被抓。这条经验即第 23 条约定。

**M5 是一个"只泄漏、不损坏"的缺陷，无法构造失败场景。** 删掉
`onClientDisconnected()` 里的 `m_decoders.remove(client);` 后测试仍通过。
原因是 `deleteLater()` 之后新连接拿到的是**全新的 `QTcpSocket` 对象**，
其 `QHash` 键与旧的**不同**，陈旧条目根本不会被命中 —— 它只是让映射表
无限增长（**泄漏**），不会造成串味。

为确认这一点我另写了真实探针（8 次"连接-断开-重连"，观察
`nextPendingConnection()` 返回的指针值）：**8 次得到 8 个互不相同的指针**，
未观察到地址复用。因此当前无法复现失败。

保留该行 `remove()` 与那条用例（一旦分配器真的复用了地址，串味会发生且极难
定位），但在测试里**如实标注"不具区分度"**，而不是写一个看起来在防这件事、
实则空转的断言。这条经验即第 24 条约定。


---

## 关键约定（由自动化检查强制）

以下二十六条是本工程最容易在重构中被悄悄破坏、又最难靠运行测试发现的约定。
`tools/verify.py` 已把它们变成提交前即可拦截的结构化检查。

### 1. 音视频通道只在接听后建立

`CallSession` 的 socket / 音频设备必须在 `Form_phonecall::engageCall()`
（即用户上滑接听）之后才创建，不能在待机时占用端口与设备。
由 `check_media_gated_by_answer` 强制。

### 2. `WA_DeleteOnClose` 的窗口不能存进裸指针成员

设了 `WA_DeleteOnClose` 的窗口在 `close()` 时会被 Qt 直接销毁。若同时把
它保存在裸指针成员里，成员随即悬垂，之后任何 `->` 都是 use-after-free。
请改用 `QPointer<...>`（它在对象销毁时自动置空）。
由 `check_deleted_on_close_members` 强制。

### 3. 常驻轮询定时器必须可停

周期性 `QTimer` 若只在局部变量里创建、又只由某个成功分支停止，就会永久空转。
若回调里还有阻塞调用（如串口读），会持续卡住 GUI 线程。定时器要存成成员，
并提供在退出/析构时调用的停止方法；分步之间的 `singleShot` 还要用代数令牌
作废（避免退出后又被延时回调拉起来）。
由 `check_unqueued_poll_timers` 强制。该检查**只覆盖 QWidget 子类**——
随程序存活的 QObject 其常驻轮询是设计意图，不算“界面空转”类缺陷。
但这类轮询器**仍然必须持有句柄**，理由见第 6 条（设备互斥）。

### 4. 收 UDP 包必须检查 `readDatagram()` / `recvfrom()` 的返回值

先 `resize(pendingDatagramSize())` 再 `readDatagram(...)` 的写法里，
**返回值不能丢**：

```cpp
QByteArray datagram;
datagram.resize(socket->pendingDatagramSize());
socket->readDatagram(datagram.data(), datagram.size(), &sender, &senderPort);
```

两个后果：

1. `QByteArray::resize()` **不清零**新分配的字节。若实际读到的字节数少于
   `pendingDatagramSize()`，尾部就是未初始化内存（或上一轮循环的残留字节）。
   音频路径下它会被 append 后直接喂给声卡（噪声）；视频路径下会交给
   `loadFromData()` 解码（垃圾数据，甚至解码器崩溃）。
2. 返回 `-1` 表示读取失败，此时 `readDatagram` **不会填充** `sender`/`senderPort`
   出参。音频路径若不判就赋值，会把“回传目标地址”改成未初始化（或上一次的）
   地址，导致后续上行语音全部发错地方。

注意 `pendingDatagramSize()` 返回 `qint64` 而非 `int`。

正确写法（`monitor_client.cpp` 采用）：

```cpp
const qint64 bytesRead = m_socket->readDatagram(datagram.data(), datagram.size());
if (bytesRead < 0) {
    continue;                 // 失败：丢弃该数据报
}
if (bytesRead < datagram.size()) {
    datagram.resize(static_cast<int>(bytesRead));
}
```

由 `check_datagram_read_returns` 强制（覆盖 `readDatagram` 与 `recvfrom`）。

### 5. `connect()` 的第二个实参必须是信号

Qt5 的 PMF 版 `connect` 会把第二个实参（成员函数指针）交给
`QObject::connectImpl()`，后者用 `QMetaObject::IndexOfMethod()` 反查信号索引，
而 **moc 只为 `signals:` 区声明的成员生成信号索引**（槽与普通成员索引为 `-1`）。
因此把一个槽或普通成员当作信号源去连接，编译能过、运行期必然失败：

```
QObject::connect: signal not found in <类名>
```

`connect` 返回 `false`，**对应的槽永远不会被调用**——那段业务逻辑是死代码，
而且不会有任何崩溃或报错提示，极难发现。

注意区分：`connect(btn, &QPushButton::clicked, this, &Cls::someSlot)` 是**完全正常**
的写法——槽只需可调用，不必是信号。本检查因此**只看第二个实参**。

由 `check_connect_signal_is_signal` 强制：解析每个 `Q_OBJECT` 类的
`signals:` / `slots:` / 访问权限分区，若 `&Cls::name` 中的 `name` 在该类的
非 `signals` 区被显式声明，即报错。继承自 Qt 基类的信号不予判定。

### 6. 共用同一硬件的轮询器必须能被他方暂停

若一个周期性 `QTimer` 的回调里做的是**阻塞式读设备**（串口 `readPacket`、
`waitForReadyRead`、`waitForBytesWritten` 等），它就会和任何其他同样访问
该设备的流程互相抢读应答——两边的读操作互为对方之应答源，结果是
“偶发失败”但找不到原因。

要互斥，前提是**拿得到定时器句柄**（才能暂停它）。因此这类轮询器不能写成
局部变量：

```cpp
QTimer* timer = new QTimer(this);        // 局部：外部拿不到句柄，无法暂停
connect(timer, &QTimer::timeout, this, [=]() mutable {
    port->sendPacket(pkt);
    QByteArray resp = port->readPacket(500);   // 阻塞读
});
timer->start(500);
```

请改为成员句柄，并提供 `setSuspended()` / `stop()` 之类的入口。
另外，函数内 `static` 标志位（如 `static bool waitingFinger`）为所有实例
共享且不随实例销毁复位，应改为成员变量；只对 lambda 可见的可变计数器
不要用裸 `new`（成功路径才 `delete`，早退即泄漏），改用
`QSharedPointer<T>` 按值捕获。

由 `check_blocking_poll_has_handle` 强制。它与第 3 条互补：第 3 条只覆盖
「QWidget 子类、`close()` 后界面空转」，本条覆盖其余常驻轮询器的
**设备互斥**需求。门口机（T113）的 `FingerprintManager` 就真实存在这个问题
（常驻识别与指纹注册抢同一个串口），本工程当前无该形态代码，本条为
预防性对称检查。

### 7. 数值配置必须在取值出口做范围兜底

配置（JSON 文件、环境变量）是**不可信输入**。环境变量经
`QString::toInt()` / `toUShort()` 解析时，非法文本会**静默返回 0**；
JSON 里也可以直接写 0、负数或超出 `quint16` 的值。

本工程受影响的是这两个：

- `signaling_port` 配成 0 → `QTcpServer` 绑定到**随机临时端口**，
  门口机仍按 8887 连接，表现为「永远连不上」且日志里看不出原因；
- `ringtone_volume` 越界 → `QMediaPlayer::setVolume` 的行为未定义。

门口机那边同一模式已经造成**真实崩溃**：重构前是硬编码
`const int detect_interval = 10;`，改成 `cfg.faceDetectInterval()` 后，
配置为 0 就在 `++detectCounter % cfg.faceDetectInterval()` 处触发整数
除零（`SIGFPE`，进程直接崩溃）。

修法是在**取值出口**统一兜底（`app_config.h` 的 `clampInt()`），
所有调用方一次性被覆盖，且合法值（默认值与示例配置）经兜底后不变：

```cpp
quint16 signalingPort() const {
    return static_cast<quint16>(clampInt(m_signalingPort, 1, 65535));
}
int ringtoneVolume() const { return clampInt(m_ringtoneVolume, 0, 100); }
```

由 `check_config_value_sanity` 强制（与门口机同一条规则），并且它自己也
有故障注入自检（`tools/verify_config_sanity.py`，6/6 用例）——静态规则
写错会静默失效，必须证明它真的能区分好坏代码。

### 8. 配置里公开的开关必须真的生效

第 7 条管的是「配置值不合理会崩」，本条管的是「配置值根本没人用」。

门口机已经踩过这个坑：`behavior.face_confidence_threshold` 配置项与访问器
都在，但 `FaceManager::recognize()` 里仍是硬编码 `confidence < 90`，现场把
阈值从 90 调到 60 **毫无变化**。这类「假旋钮」不崩溃、不告警，只让调参
永远无效，是最难发现的一类重构退化。

本工程同类风险最高的是 `signaling_port`：若它在 `widget.cpp` 的消费点
（`m_signaling->listen(cfg.signalingPort())`）被误删，门口机就再也连不上，
而程序不会报任何错。

由 `check_config_knobs_are_used` 强制，自检见
`tools/verify_config_knobs.py`（6/6 用例）。判据是「访问器在
`app_config.*` 之外被调用，**或**其成员在加载代码之外被读取」——
后一条是为了不误伤有效配置。特别地，**加载代码里的读取不算消费**：
`m_x = jsonInt(o, "x", m_x)` 只是回退实参，若把它算作消费，假旋钮就会被
漏掉（该规则第一版正是这样漏掉了门口机的 `faceConfidenceThreshold`）。

### 9. `signals:` 里声明的信号必须真的会被发射

一个只声明、从不发射的信号是**死信号**：任何 connect 到它的槽永远不会被
调用，而编译、链接、静态检查全都不会报错。

门口机已经踩过这个坑：`AudioSenderThread::connectionLost()` 被声明、被连接，
connect 的注释还明确写着用途——

```cpp
// 采集线程报告连接丢失时立即挂断，避免通话卡死。
connect(m_audioSenderThread, &AudioSenderThread::connectionLost,
        this, &Widget::hangUpCall);
```

——但全工程从未 `emit` 过它。于是 sendto 失败后采集循环 break、线程结束，
再无任何帧发往室内机，通话已单向静音，界面却依旧显示“通话中”，用户只能
手动挂断。这条“避免卡死”的兜底实际是死的。

本工程当前无死信号，本条作为**回归防护**存在：通话链路依赖
`accepted` / `answered` / `hangupClicked` / `videoFrameReady` 等信号，一旦
有人把它们改成“只声明不发射”，通话会静默失效且难以定位。

判定一个信号“真的会触发”只有两种途径：

1. 被显式发射：`emit S(...)` 或直接调用 `S(...)`；
2. 作为 connect 的**第 4 个实参**出现（信号→信号链式连接，
   `connect(btn, &QPushButton::clicked, this, &Cls::S)`）——源信号触发时
   Qt 会自动发射 S。

第 2 条不能漏：漏掉就会把链式目标误判为死信号。反过来也要注意，
`connect(this, &Cls::src, this, &Cls::dst)` 里的 `src` 是**源**，它自己
必须另有 emit 出口，否则整条链依然永不触发（检查会正确地报 `src` 是死的）。

由 `check_declared_signal_is_emitted` 强制，自检见
`tools/verify_dead_signal.py`（10/10 用例）。

### 10. connect 实参必须能正确切分（`->` 陷阱）

第 5 条（`connect` 第二实参必须是信号）依赖“按顶层逗号切分实参”。而本工程
最常见的写法首实参就含 `->`：

```cpp
connect(ui->addface, &QPushButton::clicked, this, &Form_finger::addFaceRequested);
```

若切分器把 `>` 也当作需要配对的括号（`if ch in "(<[" / elif ch in ")>]"`），
每遇到一个 `->` 深度就偏负一次，**顶层逗号再也分不出来**，整条实参列表被当成
1 个实参；检查随后因 `len(args) < 2` 直接 `continue`，**静默跳过这条
connect**——既不报错也不提示。

门口机就因此漏检了 6 条 connect（33/39）。现在切分只让 `()`/`[]`/`{}` 参与
配对，`->` 与 `>>` 不计数。由 `tools/verify_connect_signal.py`
（5/5 用例，含“首实参含 `->` 且第二实参是槽”的真阳性）锁定。

### 11. 异步播放任务必须全部等待，不能只留最后一个

门口机的 `AudioManager::playAsync()` 每次播放都覆盖同一个成员：

```cpp
stop();                                     // 置旧标志
interruptFlag = std::make_shared<std::atomic<bool>>(false);
playFuture = QtConcurrent::run([=]() { ... 捕获 this ... });
```

`QFuture` 赋值**不会等待**上一个任务（只转移内部 d 指针的引用，`~QFuture()`
也不阻塞）。所以上一次播放若尚未结束，它就变成"被丢弃但仍在运行"的任务：

- 它捕获的 `flag` 已不再是 `interruptFlag` 指向的对象，`stop()` 再也打不断
  它 —— 会把整段提示音播完，并继续持有静态 `pcmMutex`；
- 析构只 `waitForFinished()` **最后一个** future，旧任务完全不被等待，于是
  析构返回后它仍在 `emit` 信号、读成员 —— use-after-free。

修法是把所有未完成任务收集起来、析构时逐个等待（`QVector<QFuture<void>>`
+ `waitForAllTasks()`），且必须先 `stop()` 再等，否则析构会阻塞到整段音频
播完。

本工程当前未使用 `QtConcurrent` / `QFuture`，本条作为**回归防护**存在：一旦
有人为天气请求或媒体播放引入 `QtConcurrent`，这种"每次覆盖同一个 QFuture"
的写法会立刻被拦下。由 `check_abandoned_async_tasks` 强制，自检见
`tools/verify_abandoned_task.py`（5/5 用例）。注意**不误伤即发即忘的用法**：
不把结果赋给任何变量、且自带 `QPointer` 守卫的任务不存在"被覆盖丢弃"问题。

### 12. 可独立构建的子工程 CMake 必须自包含

`tests/CMakeLists.txt` 这类**既能作为主工程的子目录、又能被单独
`cmake -S tests`** 的文件，必须自带 `cmake_minimum_required()`、`project()`、
`enable_testing()`，以及 `set(CMAKE_AUTOMOC ON)`（当测试文件里
`#include "test_xxx.moc"` 时）。作为子目录时这几行幂等，两种用法都安全。

| 必须有 | 缺了会怎样 |
|---|---|
| `cmake_minimum_required()` | 配置阶段直接失败 |
| `project()` | 同上 |
| `enable_testing()` | **构建成功，`ctest` 报 `No tests were found!!!`** |
| `set(CMAKE_AUTOMOC ON)` | `fatal error: test_xxx.moc: No such file or directory` |

第三种最危险：构建退出码为 0，看起来一切正常，**实际一个用例都没执行**。

用 `check_subproject_cmake_is_selfcontained` 强制，自检见
`tools/verify_subcmake.py`（8/8 用例）。

### 13. `fromHex()` 的输入必须先逐字符校验

`QByteArray::fromHex()` **不会**因为遇到非法字符而失败 —— 它会**跳过**非法字符，
把剩下的合法字符**重新两两配对**。已用真实 Qt 5.15.19 实测确认：

| 输入（偶数长度） | fromHex 结果 | 说明 |
| --- | --- | --- |
| `FD034C12045DDF` | `fd 03 4c 12 04 5d df` | 正确 |
| `FD0G4C12045DDF` | `0f d0 4c 12 04 5d df` | **内容全错** |
| `XX034C12045DDF` | `03 4c 12 04 5d df` | **错位，少一字节** |
| `FD034C12045DDZ` | `0f d0 34 c1 20 45 dd` | **错位** |

只要字符数是**偶数**，解码就总是"成功"，`!bytes.isEmpty()` 完全拦不住。
一条写错的灯控指令会被原样写进串口，灯只表现为"没反应"，排查时极易怀疑硬件。
而"把某一位敲成字母"（`FD0G…`）恰恰最容易发生。

`parseHexBytes()` 原来只检查"非空"与"长度为偶数"，因此必须补上显式校验：

```cpp
if (compact.isEmpty() || compact.size() % 2 != 0) return QByteArray();
if (!isHexOnly(compact)) return QByteArray();   // 关键，否则上面那条守卫形同虚设
return QByteArray::fromHex(compact.toLatin1());
```

由 `check_hex_parse_is_validated` 强制：把**变量**传给 `fromHex` 而未先做
十六进制校验即报错（传给 `fromHex` 的**字面量**不受影响）。

自检见 `tools/verify_hex_parse.py`（5/5），并且本行为还有**可执行断言**：
`tests/test_app_config.cpp` 直接用真实 Qt 跑出上表的结果，把 Qt 的语义钉死
（若将来 Qt 改变该行为，测试会失败并提醒重新评估守卫是否仍必要）。

### 14. 配置载入必须在每次调用开头复位"已载入"状态

`AppConfig` 是**单例**且 `load()` 可被多次调用。原实现只在成功分支里写
`m_loadedFromFile = true`，末尾却 `return m_loadedFromFile;`，而
`applyDefaults()` 只重置各字段、**不复位该标志**：

```cpp
load(好文件)   // -> true
load(坏文件)   // 解析失败走 continue，标志仍是 true -> 返回 true！
load(不存在)   // 同样返回 true，configPath() 还指向早已失效的旧文件
```

实测（真实 Qt）确认：`load(bad)` 返回 true 且 `configPath()` 仍是上一个文件。
调用方据此认为"配置已按文件生效"，实际用的是内置默认值 —— 一个会误导现场
排查的错误返回值。

修法是在函数开头显式复位 `m_loadedFromFile = false; m_configPath.clear();`。
门口机侧用的是**函数局部** `bool fileLoaded = false;`，天然无此问题 ——
正是这个不对称让本缺陷一直没被发现，故两个仓库都保留该检查。

### 15. 配置整数转窄类型前必须先夹取

```cpp
m_signalingPort = static_cast<quint16>(jsonInt(net, "signaling_port", ...));
```

`static_cast` 到 `quint16` 是**取模截断**，不是夹取。实测（真实 Qt）：

| 配置值 | 取模结果 | 应该 |
| --- | --- | --- |
| 65536 | **0** → 随机临时端口 | 65535 |
| 999999 | **16959** | 65535 |
| -1 | **65535** | 1 |
| -5 | **65531** | 1 |

用户写 `65536`/`-1` 这类"明显想表达边界"的值时，得到的是能成功监听的**错误
端口**：门口机连不上，而日志显示监听正常。必须先 `clampInt(..., 1, 65535)`
再转换；环境变量路径同理（`toUShort()` 对非法文本返回 0，`static_cast` 同样
会取模）。

两条均由 `check_load_state_reset` / `check_narrowing_cast_of_config` 强制，
自检见 `tools/verify_config_state.py`（7/7）。

### 16. 两个仓库的测试目标名必须唯一

门口机与室内机各有 `tests/CMakeLists.txt`，目标名原本都是 `test_protocol`、
`test_app_config`。单独构建都好，但把两个仓库作为子目录放进**同一个** CMake
工程（跨仓库集成，或 IDE 一次性载入）时直接配置失败：

```
add_executable cannot create target "test_protocol" because another
target with the same name already exists.
```

实测：修复前 `configure_rc=1`，两个 `add_executable` 全部失败；给目标名与
ctest 用例名加仓库前缀（`desktop_` / `t113_`）后，超级工程 **5/5 用例通过**。
`add_test(NAME ...)` 的用例名同理——重名会让 `ctest -R` 一次选中两个。

由 `check_cross_repo_test_targets_are_unique` 强制（需传入另一仓库根目录，
见 `tools/verify_cross_target.py`，5/5）：

```bash
python3 tools/verify.py . ../Accessterminal_T113
```

用 `.clang-format` 统一格式，但**格式不是正确性**——上述二十二条请以
`verify.py` 的结果为准。



---

### 17. 影响线上字节格式的协议常量必须被测试钉住

两个仓库共享同一份 `protocol.h`。室内机是 UDP 12345 的**接收方**，按包直接把
裸 PCM 喂给 ALSA，所以采样率、声道数、每包帧数这类常量错一点，现场只表现为
"声音不对/有杂音"，**不报任何错误**。

`verify.py` 的 `check_wire_format_constants_are_pinned` 要求
`kAudioSampleRate` / `kAudioChannels` / `kAudioBytesPerSample` /
`kAudioFramesPerPacket` / `kSignalingPort` / `kAudioPort` / `kVideoPort` /
`kPreviewPort` 都必须出现在 `tests/` 的源码里。它不能证明断言写得好，但能保证
"改了这些值而测试毫无反应"不会悄悄发生。自检见 `tools/verify_wire_format.py`（7/7）。

### 18. 非阻塞打开的 PCM 句柄必须区分 `-EAGAIN` 与真错误

`snd_pcm_open(..., SND_PCM_NONBLOCK)` 打开的句柄，在播放缓冲满或采集缓冲空时
**必然**返回 `-EAGAIN`。这是**正常且可恢复**的状态，不是设备故障；当成一般
错误处理会导致静默的单向无声。

`verify.py` 的 `check_nonblock_pcm_handles_eagain` 会挑出"以非阻塞方式打开，
却在同一函数体内完全没有提及 `EAGAIN`/`EWOULDBLOCK`"的读写调用点。它按
**函数体**判定（不是整个文件），自检见 `tools/verify_nonblock_pcm.py`（6/6）。

桌面端目前没有 ALSA 代码，该规则当前为空转；同步过来是为了将来加入播放逻辑时
立刻生效，并且保证两个仓库的规则集合不漂移。

### 19. 图像编码质量属于线上字节，必须被逐字节断言

`QImage::save(&buffer, "JPEG", quality)` 的质量参数**不改变可解码性**，只改变
字节。因此"质量被改动"是一类**静默的线上差异**：带宽与画质变了，接收端照样
能解码，谁也不报错。

只校验"是 JPEG 魔数 + 能解码"是**不够的**。对照实验证实：把通话视频的质量
从 75 改成 1，原有测试**全部仍然通过**。

正确做法是把收到的数据报与本地同一张图、同一个显式质量参数编码出的字节做
**逐字节比较**，并补一条"换一个质量必须产生不同字节"的反向断言，证明该比较
有区分度。注意期望值必须**显式写出质量数**（如 75），不能也用默认质量——
那样比较会退化成"默认 == 默认"，完全不校验编码参数。

> 附带澄清：Qt5 的**默认 JPEG 质量实测恰好等于 75**（遍历质量 1..100 逐一
> 比对字节得出）。因此 `save(..., "JPEG")` 与 `save(..., "JPEG", 75)` 输出
> 逐字节相同 —— 这个"看起来的参数差异"实际不存在，已固化为断言。

### 20. 只写"停止"是不够的，必须断言"停止之后还能重新开始"

状态机类代码里，`stop` 分支常有一行把状态置回初始值的赋值（如
`CameraUdpServer::onReadyRead` 里 `stop` 分支的 `sending = false;`）。
这行赋值对"停止"本身往往是**冗余**的 —— 实测去掉它，停止行为完全不变，
线上字节一模一样，因此**任何只测"停止后不再发"的用例都发现不了它的缺失**。

它真正的作用在**恢复**路径：若停止时没有复位，再次启动的条件判断
（`if (!sending) sendTimer->start();`）就不成立，**第二次使用永远起不来**，
而界面不报任何错。

因此对"有开始/有停止"的通路，必须覆盖完整序列：
**开始 -> 收到数据 -> 停止 -> 再次开始 -> 必须能再次收到数据**。

该约定由 `check_gated_wire_paths_have_resume_test` 机械强制：它识别
"`if (!X) { X = true; ... start(); }` + `X = false; ... stop();`" 形式的
布尔闸门对，并要求 `tests/` 里出现"恢复"语义的用例或标记。
自检见 `tools/verify_gated_resume.py`（5/5 用例）。
### 21. 加了解析路径的"外层守卫"后，必须断言它**独有的**可观测效果

一个流程里同一条件常出现**两次**（入口守卫 + 回调内让路）。只断言"最终没有
产生副作用"时，**两道守卫互为遮蔽**：去掉入口守卫，回调内的守卫仍会在一轮
之内兜住，"没有副作用"照样成立 —— 入口守卫于是成了**未被验证**的代码。

正确做法是找到入口守卫**独有的**那个可观测效果。`FingerprintManager::
startIdentify()` 里它在建定时器**之前**就发出"请按下指纹"的提示信号；回调内
的守卫在 500 ms 后才触发，**无法**补救这次提示。因此要断言"挂起时连提示都
不发"，而不只是"不下发帧"。

第 21 轮的对照实验正是这样发现两道守卫互相遮蔽的（首版 7 个对照项里有 5 个
"测不出来"，全部源于只断言了不下发）。

### 22. 夹具里的取值必须让断言**可能失败**

`STORE_CHAR` 的 id 高字节断言用 `id = 0x0005` 时，其高字节本来就是 `0x00`，
把源码里的 `id >> 8` 改成常量 `0x00` 测试**照样通过** —— 断言形式正确，
但取值让它没有区分度。改用 `0x0105`（两个字节都非零）后立即暴露。

规则：凡是"大端拆分"或"逐字节比较"类的断言，**取值必须让被拆分的各个字节
互不相同且非零**，否则应视为断言无效。同理，夹具里的函数名/宏名要**恰好**
匹配被测规则的匹配模式（本轮另有 `startTimer()` 不匹配 `\bstart\s*\(`
的实例，只因仓库里恰好存在真实文件才没暴露）。
### 23. 断言"最终出现了什么"是不够的，还要断言"在错误的一侧发生之前什么都没出现"

`decodersArePerConnection` 首版只断言"最终出现了一条 `Call`"。而"所有连接
共用同一个解码器"这个 bug **恰好也能产生一条** `Call`（A 连接的前半 + B 连接
的后半拼起来），于是测试照样通过 —— 断言形式没错，却完全没有区分度。

正确写法是在**错误的那一侧动作之前**插入一个否定断言：

```cpp
a.write("cal");  b.write("l\n");
QTest::qWait(300);
QCOMPARE(spy.count(), 0);   // ← 这一条才真正有区分度
a.write("l\n");            // 只有补上 A 自己的后半，才应出现 Call
```

推广：任何"多方各自持有状态"的逻辑（按连接/按线程/按设备的映射），
都要断言"**串味不会发生**"，而不只是"正确的那种情况最终能成功"。
第 22 轮的对照实验（M4）正是这样抓到首版测试的空转断言。

### 24. 无法构造失败场景的防御性代码，如实标注"不具区分度"，不要写空转断言

`SignalingServer::onClientDisconnected()` 里的 `m_decoders.remove(client);`
在对照实验（M5）中删掉后测试**照样通过**。深查后确认它守的是一个**只泄漏、
不损坏**的问题：`deleteLater()` 之后新连接拿到的是全新 `QTcpSocket` 对象，
`QHash` 键不同，陈旧条目不会被命中，只是让映射表增长。另用真实探针实测
8 次连接-断开-重连得到 8 个互不相同的指针，未观察到地址复用，因此无法构造
可复现的失败场景。

处理方式：**保留代码与用例**（防御纵深 / 一旦分配器复用地址就会出问题），
但在用例里明确写下"本用例不具区分度"及其原因。宁可让读者知道这条断言守不住
什么，也不要写一条看起来在防、实则永远为真的断言 —— 后者会让人误以为那块
代码已经被验证过了。

### 25. 有测试 ≠ 被测到：先确认被测代码在不在执行路径上

门口机仓库第 21 轮给 `FingerprintManager::startEnroll()` 写了 26 个用例并
全部通过，第 23 轮才发现它在整个工程里**没有任何调用者** —— 现场跑的是
`Form_finger` 里另一套内联状态机。这是"有测试 ≠ 被测到"的升级版：不是断言
没落在输出上，而是**被测对象根本不在执行路径上**。26 个绿灯与现场行为毫无
关系，而且两份实现**并不等价**（现场那套多一轮 `GET_IMAGE` 探手指）。

规则：为一个函数写测试之前，先确认它有生产调用者（或作为 connect 目标）。
`check_declared_slot_is_reachable` 现在会对"既无调用者、也不是 connect 目标"
的槽告警（本仓库无指纹代码，该规则为 no-op，同步是为了规则集对齐）。

### 26. 无法用单元测试覆盖的产线路径，用静态契约检查钉住它的线上字节

门口机的 `Form_finger` 内联注册流程无法用单元测试覆盖（UI 类，需
`parentWidget()` 上溯到 `Widget` 才能拿到串口句柄，还要真实 `QTimer` 与
提示音；造夹具比被测代码还复杂，且会**再造一份平行实现**——正是第 25 条要
消除的问题）。

但它的命令字节是**指纹模块的硬契约**，不能没人守。做法是静态抽取
`append((char)…)` 的常量与 `readPacket(超时)`，与内置期望序列比对：
`check_live_fingerprint_enroll_sequence_is_pinned`。

这与"影响线上字节格式的协议常量必须被测试钉住"（第 17 条）是同一思路的
延伸：**能用运行时测试就用运行时测试，不能用就用静态契约，但绝不能没人守**。

## 开发约定

- **标准**：C++11
- **Qt**：Qt5 Widgets；代码同时避免使用 Qt6 已移除的 API
- **格式**：遵循 `.clang-format`（4 空格缩进、100 列）

```sh
clang-format -i $(git ls-files '*.cpp' '*.h')
```

### 提交前自检

```sh
# 1. 静态一致性（include 解析、构建列表、qrc、.ui 控件引用、旧标识符、
#    前置声明一致性、JSON 配置）
python3 tools/verify.py .

# 2. 签名一致性（.h 声明 vs .cpp 定义）
python3 tools/check_signatures.py .

# 2b. 校验器自检：对 check_config_value_sanity / check_config_knobs_are_used /
#     check_declared_signal_is_emitted / check_connect_signal_is_signal /
#     check_abandoned_async_tasks / check_subproject_cmake_is_selfcontained /
#     check_hex_parse_is_validated / check_load_state_reset /
#     check_wire_format_constants_are_pinned /
#     check_nonblock_pcm_handles_eagain /
#     check_gated_wire_paths_have_resume_test /
#     check_fingerprint_ack_tag_is_validated / check_narrowing_cast_of_config
#     做故障注入。静态规则写错会静默失效，必须证明它真能区分好坏代码。
python3 tools/verify_config_sanity.py .
python3 tools/verify_config_knobs.py .
python3 tools/verify_dead_signal.py .
python3 tools/verify_connect_signal.py .
python3 tools/verify_abandoned_task.py .
python3 tools/verify_subcmake.py .
python3 tools/verify_hex_parse.py .
python3 tools/verify_config_state.py .
python3 tools/verify_cross_target.py .
python3 tools/verify_wire_format.py .
python3 tools/verify_nonblock_pcm.py .
python3 tools/verify_gated_resume.py .
python3 tools/verify_fp_ack_tag.py .
python3 tools/verify_signalspy_metatype.py .
python3 tools/verify_dead_slot.py .

# 3. 跨仓库协议一致性
python3 tools/check_protocol_sync.py

# 3b. cppcheck 静态分析（不需要编译器、不需要装 Qt，可跑在任何机器上）
#     覆盖数据流、越界、空指针解引用、初始化顺序等 verify.py 查不到的问题。
#     退出码只受 warning/error 影响，style 类仅打印。
bash tools/run_cppcheck.sh

# 4. 真实编译（静态检查无法发现类型不匹配等问题，必须实际编译）
bash tools/build_host.sh
```

第 1~3 步是静态检查，速度快但覆盖有限；**第 4 步是必要的**——
真实缺陷（如声明与定义返回类型不一致、模板无法接受 lambda、
前置声明的类名拼错）只有编译器能发现。

第 3b 步（cppcheck）介于两者之间：它不需要编译器和 Qt 就能做数据流分析，
在没有工具链的机器上也能跑，是本工程唯一可用的“半编译级”检查手段。
安装：`pacman -S mingw-w64-x86_64-cppcheck`（MSYS2）。

---

## 已知限制

- 界面尺寸按 1100×650 触摸屏设计，未做自适应布局。
- 天气接口为第三方免费服务，不可用时仅记录日志，不影响通话功能。
- 视频通道每包一帧完整 JPEG 且不重传，弱网下会丢帧（与协议约定一致，
  不可改为分片重组，否则与门口机不兼容）。
