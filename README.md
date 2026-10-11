# Accessterminal_desktop — 室内机

别墅门禁可视化对讲系统的**室内机（对讲主机 / 控制面板）**。
1100×650 无边框圆角控制面板，含来电浮层、远程监看、灯光控制与天气显示。

与门口机仓库 [Accessterminal_T113](../Accessterminal_T113) 通过
TCP 信令 + UDP 音视频协同工作。

> **准备在另一台机器上继续开发？先读
> [docs/交接与继续开发.md](docs/交接与继续开发.md)。**
> 那份文档只讲三件事：做到哪一步了、哪些没做完、下一步怎么做 ——
> 包括"本机已证明什么 / 尚未证明什么"、6 个**从未被任何测试链接**的
> 产线文件清单（含主窗口 `src/ui/widget.cpp`）、以及本项目的硬约束。
> 本文（README）是**参考手册**，那份是**交接说明**，两者互补。

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

当前 7 个目标：`desktop_protocol`（协议编解码）、`desktop_app_config`
（配置与灯控指令解析）、`desktop_signaling_server`（TCP 8887 信令服务端，
真实 socket 端到端）、`desktop_monitor_client`（**UDP 50000 远程预览客户端**，
真实 socket + 环回别名假门口机，31 个用例）、`desktop_weather_service`
（**天气获取与文案格式化**，真实 QTcpServer 当天气接口，27 个用例）、
`desktop_serial_light`（**串口灯控**，影子头替身取代 QSerialPort，
34 个用例）、`desktop_call_session`（**室内机通话：UDP 12345 双向音频 +
UDP 23456 单向视频**，socket 用真的、只替声卡，33 个用例）。

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

以下六十四条是本工程最容易在重构中被悄悄破坏、又最难靠运行测试发现的约定。
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

### 产线代码覆盖率：第一次量化，以及"93.6%"为什么是误导

第 24 轮之前本工程能说"3/3 通过"，但**从未量化过测试执行了多少产线代码**。
补上 gcov 度量后，第一个数字是 **93.6%**。把从未被链接的产线文件折进分母后，
真实值是 **16.2%**。

原因在**分母**：93.6% 只统计被链接进测试目标的文件。另有 **12 个产线源
文件（约 976 行）从未被任何测试目标链接**：

| 从未被任何测试链接的产线文件 | 说明 |
| --- | --- |
| `src/ui/widget.cpp` | 主窗口，最长的一个 |
| `src/core/media/call_session.cpp` | 通话会话 |
| `src/ui/form_phonecall.cpp` | 通话界面 |
| `src/ui/slidehintwidget.cpp` | 滑动提示控件 |
| `src/main.cpp` 及其余头文件 | — |

> 第 31～33 轮各移出一个：
> `src/core/net/monitor_client.cpp`（新增 `desktop_monitor_client` 后
> 318 行覆盖 298 行，"可达未测"降为 **0**）、
> `src/core/weather/weather_service.cpp`（新增 `desktop_weather_service`）、
> `src/hal/serial_light.cpp`（新增 `desktop_serial_light`，用影子头替身
> 取代 QSerialPort 后 89 行全覆盖）。

`tools/run_coverage.sh` 一键产出：

```
已测文件 563 行（覆盖 529）+ 未测文件约 695 行 = 分母 1258
近似总覆盖率 = 42.1%   （上表那个 94.0% 仅描述已测文件）
```

被测到的文件覆盖度本身不错：`src/core/net/signaling_server.cpp` 76/76 = 100%，
`src/core/weather/weather_service.cpp` 56/56 = 100%，
`src/hal/serial_light.cpp` 41/41 = 100%，`src/core/net/monitor_client.cpp`
可达部分 100%（无"可达未测"行），`src/core/media/call_session.cpp`
130/146 = 89.0%，合计 563 行中 529 行（94.0%）。

余下未覆盖的集中在 `src/config/app_config.cpp`（122 行测 109）、
`src/core/media/call_session.cpp`（146 行测 130）、
`src/core/net/protocol.h`（58 行测 56）：`app_config.cpp` 有 7 行
**可达未测**（L65、L154-155、L273、L275、L283-284），
`call_session.cpp` 有 9 行（L38、L71、L94、L119-121、L138-140），
`protocol.h` 有 2 行（L152、L279）——**待办看的就是"可达未测"这一列**。

> `call_session.cpp` 那 9 行是工具口径的**误分类**（见 §63）：它们是
> `startAudioSocket()` / `startAudioOutput()` / `startAudioInput()` 开头的
> "已建过就早返回 / 先拆旧的"幂等守卫。工具按"所在函数有调用者"判为可达，
> 但它们实际**不可达** —— 前提是 `stop()` 无条件把四个成员指针置空，而
> `start()` 在 running 时必定先 `stop()`、不 running 时指针本来也是空。
> 与其留着当待办，不如把**这个前提**交给规则钉住
> （`check_call_session_contract_is_pinned` 第 4 条）。

**数字正确、口径错误，比没有数字更危险** —— 它会让人停止寻找缺口。

### 27. 报覆盖率必须连**分母**一起报，否则数字本身就是误导

第 24 轮第一次量化覆盖率得到 93.6%，看着很好；把从未被任何测试目标链接的
产线文件折进分母后，真实值是 **16.2%**。差别全在口径：那个 93.6% 只统计了
被链接进测试目标的文件，另有 16 个产线文件（约 1261 行，含 `widget.cpp`）
压根不出现在 gcov 数据里。

**数字正确、口径错误，比没有数字更危险** —— 它会让人停止寻找缺口。

规则：凡声称覆盖率，必须同时给出"已测文件 / 产线文件总数"与未测清单。
`check_coverage_denominator_is_declared` 会强制 `tools/coverage_report.py`
既列出未测文件、又输出折入未测文件后的真实总覆盖率。

### 28. 故障注入的"全部仍然通过"要先怀疑**夹具**，不是被测代码

门口机侧第 24 轮给 `test_signaling_client.cpp` 做故障注入自检时，前两版夹具
都因**路径**问题而静默失效（bash 把 MSYS 路径传给 Windows Python；构建目录
用了 MSYS 的 `/tmp`，Windows 侧看不到），结果 6 个变异**全部**报"仍然通过" ——
看上去像"测试全是假绿"，实际一个变异都没注入成功。

把"夹具坏了"当成"产品有缺陷"写进结论，就是自己制造了一个假 bug。

规则：故障注入夹具必须**自证**三件事：
  1. 变异确实改动了文件（写入后重新读回比对）；
  2. 目标 `.obj` 的时间戳确实更新了（跑的确实是新二进制）；
  3. 锚点在源文件中**唯一**（`count == 1`）。
任一不满足即判**夹具错误**，不得计入"仍然通过"。

跨 shell/解释器传路径时，统一用**目标解释器认识的形式**。

### 29. 同一契约的**多份拷贝**之间没有契约：一致性必须被检查

门口机侧第 25 轮发现指纹报文的构造契约存在两份副本：生产
`src/hal/fingerprint_hailin.cpp` 的 `buildPacket()`，以及链接期替身
`tests/fake_fingerprint_device.cpp` 的 `buildFrame()`（逐字节照搬）。
所有指纹单元测试跑的都是**替身**。

后果：生产的 `buildPacket()` 覆盖率为 **0**，报文字节从未被运行时测试直接
验证过；而两份拷贝可以各自漂移——改了生产那份，替身不跟着变，测试照样全绿，
**真机报文已经错了**。

这是"平行实现"教训的又一种形态：同一**功能**有两套实现 vs 同一**契约**有
两份拷贝。后者要靠静态检查钉住两份拷贝的一致性。

规则：凡"契约被复制进测试替身"，必须有一条检查比较两份实现的**操作序列**，
且该检查要经**双向**故障注入验证（改生产要报、改替身也要报），并配一个
"两边都改成一样、应保持通过"的**对照实验**（证明它比较的是一致性，
而不是等于某个死写的期望序列）。

### 30. 优先链接**真实实现**，而不是复制一份进替身

第 25 轮查明 `HailinFingerprint::buildPacket()` 是 **public 且纯函数**——只拼
字节、不碰串口，构造函数也只设置参数不 `open()`。因此完全可以**直接链接真实
实现**来测。此前的替身方案并非必要：它为了"不依赖串口硬件"而把报文逻辑复制了
一份，反而制造了第 29 条所说的漂移风险，并让真实实现覆盖率停在 0。

规则：做链接期替身之前，先问"被测的这部分到底碰不碰硬件？"。**纯逻辑就链接
真实实现**；只有真正需要隔离硬件时才用替身。

**附带实测事实（跨工程通用）**：在**未打开的** `QSerialPort` 上调
`waitForReadyRead()` 会让 Qt5 **段错误**（探针实测退出码 139，崩溃栈在
QSerialPort 内部）。"对未打开的设备调一下看它是否优雅返回"这类想当然的用例
会让测试进程直接崩掉，而不是给出一个失败断言。

本仓库没有指纹/串口代码，故上述两条规则在此处**安全空转**（实现以"文件不存在
即返回"开头）。保留同一份实现是为了让两仓库的共享切片保持逐字节一致 ——
桌面端的 `monitor_client` 等模块将来若引入链接期替身，可直接受益。

### 31. 自检脚本必须能在**目标控制台编码**下安全输出，否则会伪装成"通过"

门口机侧第 25 轮两个故障注入自检脚本在本机崩溃：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'
```

它们用了 `✓`。本机控制台是 GBK。危险之处在**它伪装成通过**：报告前面的
检查结果已经正常输出，看上去一切正常，而 rc=1；调用方若忽略返回码或只看尾部
输出，就会读成"全绿"。

**代价是两轮误诊。** 第 24 轮遇到同一现象时，因为当时用 pwsh 且设了
`PYTHONIOENCODING=utf-8` 去测（恰好掩盖了真因），被误判为"多余参数"问题，
打了个忽略参数的补丁——治的是症状。第 25 轮在 bash、不带该环境变量时复现，
才查出真因。

规则：脚本要么把 stdout/stderr
`reconfigure(encoding="utf-8", errors="replace")`，要么不含目标控制台编不出的
字符。**逐个删符号不算修好**——第 24 轮删了 `⚠`，第 25 轮就冒出 `✓`。
`check_tool_scripts_are_console_encoding_safe` 强制此事（本仓库规则块与门口机侧
逐字节一致）。

推而广之：**"在我这儿能跑"不是验证。** 验证必须在**目标环境的确切条件**下进行
（这里是"不带 PYTHONIOENCODING 的 GBK 控制台"）。用一个恰好掩盖问题的环境变量
去测试一个环境相关问题，得到的绿色是假的。

### 32. 覆盖率要再拆一维：未覆盖 = **不可达** + **可达未测**

门口机侧第 26 轮量出 `fingerprint_hailin.cpp` 覆盖率 17.9%，像个大洞。
按可达性拆开后：

    可执行行 285
      零调用者（静态不可达，baseline 亦然）  204 行 = 71.6%
      有调用者（真的没测到）                  81 行，其中未执行 30 行

**未覆盖 234 行里只有 30 行真能靠写测试补上。** 其余是基线就没接线的死代码
（`HailinFingerprint` 的 5 个入口在生产代码里零调用者，实测 baseline 同样如此）。

只报一个百分比会**同时误导两个方向**：把死代码算成待补缺口，又把真缺口淹没。
所以：

    未覆盖 = 不可达（不是待办） + 可达未测（**待办看这一列**）

`coverage_report.py` 输出该分类并列出可达未执行的具体行；
`check_coverage_separates_dead_from_untested` 强制它这么做（本仓库规则块与
门口机侧逐字节一致）。

**规则的能力边界也要如实写清。** 这条规则是"能力存在性 + 分类标签存在性"检查，
**不能**发现"分类函数还在但被掏空成 `return {}`"—— 那需要真的跑一次脚本。
不写清边界就会高估它。

### 33. 变异"未触发"时，先证明变异真的改变了被测属性

门口机侧第 26 轮给新规则做故障注入，前 3 个用例都报"期望报错、实得通过"。
查下去是**夹具缺陷**：关键字在文件里各出现 5 次，而只替换了第一处，其余仍满足
规则 —— 规则不报错是**正确**行为。

**变异没触发时，第一嫌疑是变异没生效，不是规则失灵。**

具体到字符串替换：**替换次数要显式确认**。默认全替换，或断言替换后目标属性
真的消失（再读回文件、按规则同样的判据检查一遍）。

同时也说明：**我的期望也可能写错。** 那次我期望"函数一致改名后规则应失败"——
但改名是保持行为的重构，规则通过才是对的。这类"期望本身错了"只能靠**对照实验**
发现：凡断言"应当报错"，就配一条"改动但行为不变，应当通过"的对照。

### 34. 锚点必须唯一，且要唯一到**正确的那个函数**

门口机侧夹具的"锚点唯一"自证第一次真正发挥作用：变异目标
`if (resp2.size() < 12 || (quint8)resp2[9] != 0x00) {` 在
`fingerprint_manager.cpp` 里出现**两次** —— `startIdentify`(L143) 与
`startEnroll`(L269)。

若不收窄锚点就会改错函数：测试照样失败，但**以为**验证的是识别路径，
**实际**验证的是注册路径。两处代码几乎逐字相同，肉眼看 diff 也发现不了。

规则：锚点唯一性不够，还要**唯一到目标函数**。收窄办法是带上**只有目标处才有
的上下文**（此例是紧随其后的 `emit identifyResult(...)` vs
`emit enrollResult(...)`）。

### 35. 安全性质要有**运行期**断言，不能只靠静态文本规则

门口机侧第 27 轮查明：baseline 把**门禁密码**（明文 + 双方 hex）打进 qDebug。
重构修掉了，但守它的只有一条静态文本规则（"源码里敏感变量名没出现在日志
语句里"）。

静态规则容易被绕过：**改名、拼串、经辅助函数转一手**，正则就看不见了。所以
门口机侧补了运行期测试 —— 真的设哨兵密码、真的调校验、真的抓 `qDebug` 输出，
断言哨兵及其 hex 一次都没出现。故障注入实测 6 种真实泄漏形态全部被抓到。

**本仓库没有密码代码**（室内机不持有门禁凭据），但这条约定通用：凡是"某敏感
数据不得出现在某输出里"的性质，静态扫描只是第一道网，需要运行期断言兜底。
同步过来的 `check_password_log_regression_is_enforced` 在本仓库**直接早退**
（找不到 `src/managers/password_manager.cpp` 即视为不适用），不会误报。

### 36. "X 不出现"的断言必须配**阳性对照**，且夹具跨编码边界时要先自证

两条都来自门口机侧第 27 轮实测，都是"断言在、实则零验证"的失效方式。

**(1) "不存在"型断言要配对照。** "日志里不含密码"有个致命失效方式：若消息
处理器没装上、或日志走了别的通道，**任何**"不包含"断言都会通过 —— 测试看着很
严，实则零验证。所以每条"哨兵不出现"都配一条"**非敏感日志确实被捕获**"的
对照，捕获管道坏了对照先失败。**先证明检测手段能看见东西。**

**(2) 夹具跨过编码边界必须先自证。** 门口机侧第一版用**环境变量**注入**非
ASCII** 哨兵，然后断言"日志不含该哨兵的每个前缀"。故障注入发现"`left(4)` 前缀
脱敏"变异**抓不到**。探针查明：

```
ASCII  设定 == 取回 ? true      （26 码元 -> 26 码元）
UTF8   设定 == 取回 ? false     （13 码元 -> 16 码元）
```

`AppConfig::toQString()` 是 `QString::fromLocal8Bit()`，本机 GBK 代码页下 UTF-8
字节被按 GBK 解码。于是那条断言在比较**两个不同的串**，**恒真**。

**凡夹具跨过一次编码边界（环境变量、文件、argv），必须先断言它原样到达。**
否则围绕它的所有断言都可能是空的。

顺带：前缀断言要**逐一遍历每个前缀**，只查一个固定长度会漏掉其它脱敏写法。

### 37. 守卫条件不能引用被守卫内容里会出现的字符串

门口机侧第 27 轮新规则里写成：

```python
if "Fixture" not in text and "哨兵必须原样" not in text:
    if "doorPassword(), pwd" not in text:
        fail(...)
```

被测测试文件的**头部注释**里恰好写了"哨兵必须原样到达被测代码" —— 外层条件
恒 False，真正的断言检查**永远不可达**。故障注入"去掉夹具自证断言"因此报
"规则未触发"。

这是门口机侧第 22 轮"写了一条永远不会 fire 的规则"的同族问题。

**写守卫时要问：这个字符串会不会正好出现在我要检查的东西里？** 会，就别拿它
当门。

另外那轮夹具自己又踩了一次解析问题：verify.py 打印的是**大写** `  X [规则]`
而夹具按小写 `x` 判断，5 个用例被误报成"规则未触发"。**夹具的解析逻辑同样要
按真实输出写，并靠对照用例自证。**

### 38. 写硬件替身之前，先查清真实库的**取值范围**与**内存所有权**

门口机侧第 28 轮为 `GpioLine`（物理门锁/补光那条线）写可编程假 libgpiod。
第一版测试失败时，我两次怀疑方向**全都错了**：

1. **取值范围**：假实现给每个 chip 64 条线，而工程用 132 / 133，于是所有正常
   用例失败 —— 看着像"生产代码开不了线"，实为夹具把合法线号判成越界。
2. **内存所有权**：libgpiod 1.x 里线对象**属于 chip**（`get_line` 返回 chip
   内部的数组元素），`release` 只清"已请求"状态、**不释放内存**，`close` 才
   释放。我第一版让两者各自 `new`/`delete`，于是生产代码在"请求失败"路径里
   先 `release` 再 `close` 时被误报 `release:unknown`。

**夹具与真实 ABI 不符时，会稳定地产生假阳性 —— 而假阳性比真缺陷更像真缺陷。**
写替身的第一步是把真实库的取值域与所有权查清，不是先把测试写完。

### 39. 断言"泄漏"要数**语义资源**，不是数对象；无法验证的行为只观测不断言

**(1) 数语义资源。** 第一版用"线对象个数"判断泄漏，在错误的所有权模型下毫无
意义。对齐 ABI 后真正该数的是 **仍持有有效请求的线数**（`busyLineCount()`）：
泄漏的请求会让线一直 busy，下次开锁直接 EBUSY。并且假实现让**对已 busy 的
资源再次请求返回失败**，于是泄漏能被**端到端**抓到，而不是靠事后数数。

**度量要选成"现场会痛的那个量"。** 数错了量，测试通过也说明不了问题。

**(2) 只观测、不断言。** 生产代码在"请求失败"路径里会 `release` 一条**从未
成功请求**的线（防御性清理）。libgpiod 对该情况的确切行为无法在本机验证
（没有真实 `gpiod.h` / 库）。所以夹具提供 `releaseUnrequestedCount()` 记录它，
测试**不断言**其数值，只在注释里说明为何不断言。

**把猜测写成契约比不写更糟** —— 它会锁住一个可能错误的假设，后人改真代码时
反被此测试拦住。

### 40. 规则的"登记检查"要覆盖**全部**相关文件

门口机侧第 28 轮给 GPIO 写新规则时，我检查了 `fake_gpiod.cpp` 与
`hal/gpio.cpp` 是否列进 CMakeLists，**却漏了 `test_gpio.cpp` 本身**。故障注入
"测试未接进 CMakeLists"因此没触发 —— 测试文件存在但没人编译它时，规则会静默
放过。

**列"必须存在的引用"时，逐个文件核对，别只挑印象最深的两个。**

（本仓库的 `check_gpio_failure_paths_are_testable` 因找不到
`src/hal/gpio.cpp` 而直接早退，不适用。）

### 41. 探针的一半价值在于**否掉错误假设**

门口机侧第 29 轮为 `FaceManager`（人脸门禁：决定门开不开）写测试前先跑了三个
临时探针。除了量到"未训练的 LBPH `predict()` 抛 `cv::Exception`"与"单 label
时 `predictedLabel == 1` 恒真"这两条有用事实，还**推翻了我自己的推断**：

> 我原以为"人脸框越界 -> `QImage::copy()` 返回空图 -> 存进空样本 ->
> `train()` 抛异常 -> UI 线程崩溃"。实测 `QImage::copy()` 传越界矩形返回的是
> **指定尺寸、内容未初始化**的图，`isNull() == false`，根本不是空图。

若不做探针，我会把这条**错误**的因果链写进注释与断言里 —— 而错误断言比没有
断言更糟：它会把一个不存在的行为固定成"契约"。**记录"我否掉了什么假设"和
记录"我发现了什么"同样重要。**

### 42. 安全参数如果只有一个判据，就要把它写成断言

门口机侧探针证实：单 label 的 LBPH 模型里 `predictedLabel == 1` **恒为真**，
因此 `confidence < threshold` 是**门禁唯一的门**。门禁安全**完全**系于一个
数字。

由此两条做法：
1. 专门写一条用例把"阈值是唯一判据"这一事实钉住（松阈值 -> 陌生人也能开门；
   紧阈值 -> 必须拒绝）。丢了它，就没人守这条唯一的门。
2. 阈值断言**不硬编码 confidence 数值**，而用被测代码自己吐出的 confidence
   当基准（`阈值 = conf` 必须拒绝，`conf + 1` 必须接受）—— 既精确钉住比较
   语义（严格 `<` 而非 `<=`），又与 OpenCV 版本无关。

（本仓库的 `check_face_gate_hazard_is_documented` 因找不到
`src/managers/face_manager.cpp` 而直接早退，不适用。）

### 43. "没有判别力"的断言要当作没有断言

门口机侧 `addFaceSample` 应把彩色图转灰度再存。第一版用例只断言"彩色注册后
`train()` 成功"，理由是"不转换的话 LBPH 会抛异常"。**故障注入证明这条断言
毫无判别力**：

> LBPH 接受任何 `CV_8UC1` 的 Mat，即使那个 Mat 其实是 RGB32 缓冲的前 1/4
> 字节（`stride` 400 而 `width` 100），`train()` 照样成功。

第二个探针量出真正的判别力在**像素数据**上（注册彩色、用灰度同图案预测）：

| 图案 | 真转换 | 不转换 |
| --- | --- | --- |
| kind=0 | 0.00 接受 | 256.00 拒绝 |
| kind=1 | 0.00 接受 | 153.60 拒绝 |
| kind=2 | 0.00 接受 | **33.26 接受（无判别力）** |

于是改为"彩色注册 -> 用**灰度**同图案预测 -> 必须接受"，并**固定选 kind=0**
—— 因为 kind=2 那个图案即使实现错了也会通过。

**断言必须落在能区分正确/错误实现的输出上；而且不是所有输入都有判别力，
要挑出真的能区分的那一个。**

### 44. 规则匹配用词元边界，不要用子串

门口机侧 `[face-gate]` 规则用子串检查测试函数是否存在，故障注入抓到：
把 `thresholdIsTheOnlyGateWithSingleLabel` 改名成
`thresholdIsTheOnlyGateWithSingleLabel_removed()` 后，规则**仍然通过** ——
因为原名是改后名的**前缀**。

修法：要求严结尾，即检查 `"thresholdIsTheOnlyGateWithSingleLabel("`
（紧跟左括号）或使用**完整符号名**。**匹配一个符号时必须考虑它的边界。**

同时删掉了一条我自己写的**不成立的用例**（"去掉隐患的说明文字"）：注释文字
并非必要条件，规则用符号名做锚点是对的 —— 是那条用例过强。

### 45. QtTest 的退出码**等于 FAIL 行数**，不是崩溃信号

门口机侧第 30 轮实测（此前一直是**猜**的）：

| 变异 | 退出码 | FAIL 行数 |
|---|---|---|
| 请求输出失败时不释放线 | 1 | 1 |
| 析构不释放（RAII 完全失效） | 18 | **18** |
| `close()` 不 munmap（只关 fd） | 22 | **22** |

由此发现两件事：

1. 我此前在 `verify_gpio_test.py` 的文档里写的"多数变异是被进程崩溃抓到的，
   那些变异真的造成了 double-free / use-after-free"是**错的** —— 那些其实是
   **干净的多用例失败**。判据 `returncode not in (0, 1)` 把"多失败"当成了
   "崩溃"。
2. 更危险的是它还有**假绿**方向：真正的崩溃若恰好 `rc=1`，会被判成
   "未抓到（假绿）"，从而把一个**有效的回归测试**误删。

正确判据：**真正的崩溃 = 非零退出码但一条 FAIL 行都没有**（如访问违例
`0xC0000005`）。退出码与 FAIL 计数是否一致还可以作为交叉校验。

> 本仓库目前没有用 QtTest 退出码做判定的夹具（门口机侧新加的
> `check_fault_harnesses_classify_crashes_correctly` 在本仓库会因找不到
> 相关文件而安全跳过）。这条记录在此，是为了**将来写夹具时不再踩同一个坑**。

### 46. 规则里的 `except Exception: continue` 会把规则变成**空操作**

门口机侧第 30 轮写新规则时漏了 `import ast`，而循环体是：

```python
try:
    text = code_only(p)
except Exception:
    continue          # <-- NameError（ast 未导入）被静默吃掉
```

于是**每个文件都被跳过**，规则恒真。故障注入的"变异未被抓到"是唯一线索 ——
在它暴露之前，规则的输出与"全部合规"完全一样。

教训：自检脚本里**不要吞异常**。宁可让规则响亮地失败，也不要它悄悄通过。
**一个恒真的规则比没有规则更糟**，因为它会被当作已经守住了。

### 47. 挖注释不够，还要挖**字符串字面量**

判断"某段代码是否还在"时，正则去 `#` 注释是不够的：

- CMakeLists 的**注释**里会反复提到源文件名（解释为什么用假替身），
  于是"把 `add_executable` 里那一行删掉"这个变异**抓不到** ——
  整文件子串仍然匹配注释里的名字。
- Python 夹具的**字符串字面量**里会出现被禁止的模式（它正是用来制造变异的），
  于是夹具自己被误报。

修法：用 `tokenize` 挖掉注释**与字符串**，只在真正的可执行代码上匹配；
CMake 则先把目标块切出来（`add_executable(...)` / `target_link_options(...)`
的括号内容），在块内查名字，而不是整文件查子串。

### 48. 给 `MonitorClient` 补测试：UDP 50000 的行为契约

第 31 轮给 `src/core/net/monitor_client.cpp` 补了 31 个用例
（`tests/test_monitor_client.cpp`）。它是室内机侧 **UDP 50000 远程预览**
协议的实现者 —— 产线在跑（`widget.cpp:107/326`），此前**零**单元覆盖。

**协议（逐字节，不可改）**：PC 向门口机发**裸文本**数据报
`"getframe"` / `"stop"`，**不带换行**；门口机只在收到 `getframe` 后才推帧。
请求源自本端 **50000** 端口，因此要 `bind(Any, kPreviewPort,
ShareAddress | ReuseAddressHint)` —— 绑定失败要报 `errorOccurred` 并返回
`false`，不能"静默继续"（那样会发不出去也收不到，界面却显示已开启）。

> **陷阱**：`"stop"` 是 TCP 8887 上 `"stopsend"` 的**前缀**。UDP 侧必须是
> `stop`，写成 `stopsend` 门口机会当成完全不同的信令，预览**永远不会停**。
> 已由静态规则与故障注入双向钉住。

### 49. 两个 socket 绑同一端口时，**谁收到**不可预测；用环回别名消歧

写测试时要在本机模拟"门口机"，最自然的做法是让假门口机也绑
`Any:50000`。第 31 轮实测（探针 `result3.txt`）：**两个都带
`ShareAddress` 的 socket 绑同一地址时，数据报只投给其中一个，且不可预测**
—— 测试会随机失败。

改用**环回别名**即可确定性消歧：假门口机绑 `127.0.0.2:50000`，
被测的 `MonitorClient` 绑 `Any:50000`。实测**两个方向都稳定**，
且与绑定顺序无关（重复 5/5 次一致）：每一个 `getframe`/`stop` 都落到
假门口机，每一帧都落到 `MonitorClient`。

反向也测了（探针 `result4.txt`）：先用**独占**方式（不带 `ShareAddress`）
绑上 `Any:50000`，`MonitorClient` 的 `ShareAddress | ReuseAddressHint`
绑定会**确定性地失败**并报 "The address is protected" —— 于是错误分支
可以被真实地触发，而不是靠 mock。

```cpp
// 假门口机（环回别名，不与被测争抢同一地址）
m_socket.bind(QHostAddress("127.0.0.2"), 50000,
              QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint);
```

注意 `bind(QHostAddress::Any, 0)` 在 Qt5 里是**二义**的
（`bind(const QHostAddress&, quint16, BindMode)` vs `bind(quint16, BindMode)`）；
必须写成 `bind(QHostAddress(QHostAddress::Any), quint16(0))`。

### 50. `QPixmap` 需要 `Qt5::Gui`/`QGuiApplication`，且它**已被 Qt 注册**

`MonitorClient` 的 `frameReceived` 信号带的是 `QPixmap`（不是 `QImage`），
因此这是本仓库**第一个**必须链 `Qt5::Gui` 的测试目标；`QTEST_MAIN` 会据此
生成 `QGuiApplication`。实测 `QGuiApplication` 在无显示的 Windows 上可以
正常工作（平台插件 `windows`）。

同时实测（探针 `result10b.txt`）：`QPixmap` **已经被 Qt 自己注册**为元类型
（`QMetaType::type("QPixmap") == 65`），**不需要** `qRegisterMetaType`。
这条实测同时修掉了一个真实误报：`check_signalspy_types_are_registered` 的
内建类型集合漏了整片 GUI 类型，会把用 `QSignalSpy` 断言 `QPixmap` 的测试
误报成"缺注册"。实测**未**注册的（`QPainterPath`、`QHostAddress`、
`QMimeType`、`QTcpSocket*` 均为 0）**故意不列入**，它们确实需要显式注册。

### 51. 有些契约**行为测试根本抓不到** —— 交给静态规则，并**实测证明**抓不到

给 `MonitorClient` 做故障注入时，有三处退化**测了也抓不到**。与其写一条
看起来守着、其实守不住的断言（那比没有断言更糟，因为它会让人误以为这块
已被覆盖），不如**如实记录边界**，并改由静态规则守：

| 退化 | 为什么行为测试抓不到 | 谁来守 |
|---|---|---|
| `"JPG"` → `"JPEG"` | 实测（`result5.txt`）`QPixmap::loadFromData` 对两者**都能解码**同一份 JPEG（都 `isNull=0`、64×48） | `check_monitor_client_contract_is_pinned` 直接钉字面量 |
| `while` → 只读一个 | 实测（`result8.txt`）Qt 在数据报仍有剩余时会**再次**发 `readyRead`，两种写法最终都把帧送完：连发 50 个时 while 读 50 / 触发 **1** 次，if 版读 50 / 触发 **50** 次 | 同上（钉 `while`；20fps 下回调差是真开销） |
| 删 `if (bytesRead < 0)` 等 | 实测（`result7.txt`）按 `pendingDatagramSize()` 分配缓冲区时，`readDatagram` 返回值**永远等于**该大小（0/1/4/100/678/1400/65507 全部相等），分支**不可达** | 同上（纵深防御，不可删） |

并把"抓不到"变成**可执行的断言**：`UNDETECTABLE` 列表里的退化被要求
**必须抓不到**；一旦将来某次改动让它变得可观测，夹具会报错并提示
**把它提升为真变异**，而不是继续留在免责清单里。

> 另外注意：`while` **不能**简单改成 `if` 来制造变异 —— 循环体里有
> `continue`，会直接编译失败。用只跑一次的 `for` 才构造得出合法变异。

### 52. 静态规则**必须限定在函数体内**，否则会被别处的同名串顶包

`check_monitor_client_contract_is_pinned` 第一版检查"`widget.cpp` 里是否
出现 `!m_cameraActive`"，故障注入当场抓到：把
`Widget::onVideoFrameReady` 里那道"非活动态不收帧"的门删掉之后，规则
**仍然通过** —— 因为 `on_btngetframe_clicked` 里还有一处
`if (!m_cameraActive)`（第 328 行）替它顶了包。

修法：`_brace_matched_body()` 先剥注释与字符串，再按大括号配对**取出函数体**
只在体内查。这就是"守卫条件不得引用被守卫内容里也出现的字符串"那条规矩的
一个具体形态：**整文件子串检查是最容易变成恒真的一类规则。**

### 53. 给 `WeatherService` 补测试：一条写着"不能这样写"却从未被验证的注释

第 32 轮给 `src/core/weather/weather_service.cpp` 补了 27 个用例
（`tests/test_weather_service.cpp`）。它此前从未被任何测试目标链接。

起因是它代码里最长的那段注释（`abandonReply()` 上方）断言的是一条
**从未被验证过的因果链**。第 32 轮先用探针实测了这条链
（`%TEMP%\probe32\`），结果**一半对、一半错**：

| 实测 | 结论 |
|---|---|
| `result11.txt` | `abort()` **确实同步**投递 `finished()` —— 5/5 次，三种状态下都成立。**注释的前提是对的。** |
| `result12.txt` | 但预测的"空指针解引用**崩溃**"**没有复现** —— `nullptr->deleteLater()` 形式上是 UB，可 `QObject::deleteLater()` 只是把指针丢进事件队列、并不解引用，程序**侥幸活着**。注**描述的具体后果过强了**。 |
| `result13.txt` | 真正的、**用户可见**的后果是**假错误**：正确顺序 finished 处理 0 次/错误 0 个；错误顺序 finished 处理 1 次/错误 1 个，消息 `天气请求失败: Operation canceled (HTTP 200)`。 |

也就是说：**每次刷新天气取消上一个在途请求，界面都会闪一条"天气请求失败"**，
而实际上并没有失败。测试守的是这条真实差异
（`refreshCancelsInFlightWithoutFalseError`），注释已按实测改写。

> 教训：一句"这里有 UB/会崩溃"如果**没被验证过**，它既可能挡住一个真缺陷，
> 也可能只是把 UB 说成了必然崩溃。**UB 不等于必然崩溃** —— 这个区别会
> 影响后来者是"保留防御"还是"认定不可达而删掉它"。

### 54. 测试用假服务端时，**按键必须在断开时就清干净**

`FakeWeatherServer` 用裸指针当 `QMap` 的键记录"这条连接是否已应答"。
第一版只在 `disconnected` 里删了 `m_buffers`，**漏删 `m_answered`**。
socket 是 `deleteLater()` 释放的，堆地址被复用后，新建的 socket 很可能
拿到同一个地址 —— `m_answered.contains(sock)` 命中旧记录，于是**永远不再
应答**，客户端一直等到超时。

表现是 **1/15 次偶发失败、单独跑又全过** —— 极容易被误判成"被测代码有竞态"。
实测确认后修掉，`40/40` 次全量通过。

> 附带教训（工具层面）：我第一次"验证修复"时跑的是**旧二进制**
> （在修复前构建的目录里），于是看到"仍然 1/15 失败"并差点去改被测代码。
> **验证一个修复必须用重新构建的产物** —— 否则你验证的是修改前的世界。

### 55. 规则本身也可能**过强**，基线就不过

`check_weather_service_contract_is_pinned` 第一版把顺序写死成
`disconnect -> 摘成员 -> abort`，结果基线直接报错：真实代码是先
`m_reply = nullptr;` 再 `disconnect(...)`。两者**相对次序并不重要**，
真正不可调换的是"它们都在 `abort()` 之前"。改成 `i_disc < i_abort and
i_null < i_abort` 之后才对。

这是本规则自己的故障注入当场抓到的 —— **规则和被测代码一样需要证明**；
一条基线就不过的规则如果被"顺手放宽到能过"，往往会把真正的约束也一起丢掉。

### 56. 影子头文件：给"具体类型"的第三方依赖做测试替身

`src/hal/serial_light.cpp` 第 33 轮才首次进测试。它把 `QSerialPort` 当
**具体类型**用（`new QSerialPort(this)`、`m_port->write(...)`），既非虚函数
也不可注入，而开发机上没有真实串口。两条路都试过：

| 办法 | 结果 |
| --- | --- |
| Windows 命名管道冒充串口（`setPortName("pipe\\x")` -> `\\.\pipe\x`） | **放弃**：实测卡在 `QSerialPort::open()`，且依赖 `\\.\pipe\` 平台细节 |
| **影子头文件** | **采用**：把替身命名为 `QSerialPort` 放在 `tests/fake_serial_port/`，用 `target_include_directories(BEFORE ...)` 插到 Qt 的 include 路径之前 |

已用探针确认影子确实生效（`%TEMP%\probe33\shadow.cpp`，影子生效时退出码 0）。
于是测的仍是**真实的 `serial_light.cpp`**、同一条代码路径，只把最底层的
系统调用换成可记录的替身；"打开失败要发信号"、"写入不完整要发信号"、
"未打开不许写"这些分支都能真的被执行到。

三条必须记住的配套要求：

1. **影子头必须自带 `#error` 安全阀**（要求显式定义 `ACC_SERIAL_LIGHT_TEST`）。
   它会**顶掉**真正的 Qt 头 —— 万一被产线目标误命中，产线就拿替身跑，而且
   编译链接**一切正常**。这是最危险的一类错误。
2. **必须带 `BEFORE`**。少了它影子头排在 Qt 之后，`#include <QSerialPort>`
   仍命中真 Qt 头，而测试表现是"链接期缺少 QSerialPort 的符号"，极易误判。
3. **替身不要加 `Q_OBJECT`**。它不在任何目标的源列表里，AUTOMOC 不会处理，
   加了会因缺 moc 输出而链接失败（`SerialLight` 也从不 connect 它的信号）。

### 57. 故障注入的判定：**别去匹配用例名的形状**

第 33 轮发现一个潜伏在已有夹具里的 bug。判"是否崩溃"用的是
`returncode != 0 and not failed`，而 `failed` 来自

```python
re.findall(r'^FAIL!\s*:\s*\w+::(\w+)\(\)', out, re.M)   # 过窄
```

数据驱动用例输出的是 `FAIL!  : Class::case(desk)`，**不是** `case()`。
于是那条用例失败时 `failed` 为空 -> 退出码非零 -> 被判成**崩溃**。
实测：把 `desk` 指令的一个字节改掉，一条正常的断言失败被报成
"崩溃(rc=1, 0 条 FAIL 行)"。

正确写法是只看行首标记，不依赖用例名的形状：

```python
re.findall(r'^FAIL!\s*:', out, re.M)
```

`verify_monitor_client_test.py` 与 `verify_weather_service_test.py` 里同款
正则已一并改掉 —— 它们当时只是**碰巧**没有数据驱动用例才没暴露。

### 58. 静态规则要**剥掉注释**再检查

`check_serial_light_contract_is_pinned` 第一版检查影子头里有没有 `#error`
安全阀，写法是 `"#error" not in shim_text`。故障注入把安全阀整段删掉之后
规则**仍然通过** —— 因为头顶的**文档注释**里就写着"否则直接 `#error`"，
替真指令顶了包。

同理，检查 `tests/CMakeLists.txt` 是否引用 `fake_serial_port` 目录时，
只搜子串也不行：源文件列表里的 `fake_serial_port.cpp` 会顶包。必须正则匹配
真正的 `target_include_directories(...)` 调用。

> 这是"**守卫条件不得引用被守卫内容里也出现的字符串**"那条规矩的又一变体，
> 只不过冒出来的出处是**文档注释**和**同名字源文件** —— 两者都极其自然，
> 所以更容易中招。

### 59. 用 `_brace_matched_body` 就只能看代码，看不了字符串

`_brace_matched_body()` 走的是 `strip_comments_and_strings()`，而后者会把
字符串字面量**清空**（只留定界符）。于是任何"按函数体内某个**字符串**的
相对位置判断"的规则必然失效：待比较的两个东西本身就是字符串字面量，
剥掉后 `find()` 全返回 -1。

因此新增了 `_brace_matched_body_with_strings()`，返回**保留字符串的原文
切片**。它用新写的 `_strip_comments_keep_length()` 定位括号 —— 后者的关键
性质是**逐字符等长**（行注释也换成空格而不是删掉），下标因此可以直接用来
切原文。

> 注意：不要指望 `strip_comments_and_strings()` 保长 —— 它把行注释**整段
> 删除**（实测 `serial_light.cpp`：2105 字符 -> 1878 字符）。新函数里有一道
> `len(code) != len(text)` 的断言，长度一旦不等就返回 `None` 让调用方报
> "规则自身需修复"，绝不悄悄用错位的切片。

### 60. 双工通话：**socket 用真的，只替声卡**

`src/core/media/call_session.cpp`（298 行）此前**从未被任何测试目标链接**，
却是两条协议硬约束的室内机一侧：

- **UDP 12345** 双向音频，裸 PCM（S16_LE / 16000Hz / 单声道），**无包头**，
  每包 320 帧 / 640 字节；
- **UDP 23456** 单向视频，门口机 → 室内机，每包一帧**完整 JPEG**，
  不重组、不重传。

门口机那侧有测试、室内机这侧没有 —— 于是门口机改了字节，这边仍然全绿，
而互操作已经断了。

**关键决定：端口是协议常量，不能挪到别的端口去测。** 第 31 轮的
`MonitorClient`（UDP 50000）测法是把端口参数化到临时端口，因为它本来就
接受端口注入；`CallSession` 不行 —— `12345`/`23456` 是写死的协议常量，
编造一个"可注入端口"的接缝就等于改产品代码去迁就测试。所以这里让
`CallSession` 在**真实协议端口**上收发，用另一个 `QUdpSocket` 充当门口机。

探针实测（`%TEMP%\probe34\result17.txt`）确认本机可行：

```
bind(AnyIPv4,12345,ShareAddress) = true
readDatagram -> 640 字节  sender=127.0.0.2:52803（与发送端一致）
bind(Any,23456,ShareAddress)     = true
```

**只有声卡是替身。** 本机确实有可用音频设备（探针 `result16.txt`：
`QAudioOutput::start()` 非空、`QAudioInput::start()` 非空），但把单元测试
绑在**开发机的真实声卡**上，结果就取决于那台机器（有没有声卡、是否被独占、
支不支持 16k 单声道）——那正是"在我这儿能跑"的坑。替身让音频路径完全确定。

替身机制沿用第 56 轮的**影子头**：`tests/fake_audio/` 下放名为
`QAudioFormat` / `QAudioInput` / `QAudioOutput` 的头，用
`target_include_directories(... BEFORE PRIVATE ...)` 插到 Qt 的 include 之前；
每个影子头都带 `#ifndef ACC_CALL_SESSION_TEST` + `#error` 安全阀。因为三个
音频类全被替换，本目标**不需要** `Qt5::Multimedia`。

> `QAudioFormat::bytesPerFrame()` 的替身实现必须与真 Qt **逐位一致**
> （`(sampleSize/8) * channelCount`，任一参数未设置则 0）：被测代码用它算
> `bytesPerMs = bytesPerFrame()*sampleRate/1000`，进而算缓冲区大小 —— 那是
> **产品的行为**，不能被替身悄悄改掉，否则断言的不是产品而是替身。

结果：`desktop_test_call_session` **33 个用例**；故障注入
`verify_call_session_test.py` **22 个变异全部被抓到**，另有 5 个**实测无
判别力**的退化如实记录（见 §62）。

探针 `result18.txt` 给出了可靠的失败路径造法：先用一个 socket **独占**绑住
端口，`CallSession` 的 `ShareAddress` 绑定就必然失败（3/3 稳定复现），
于是 `audioBindFailureEmitsError` / `videoBindFailureEmitsError` 不再是
"碰运气能不能造出失败"，而是确定性的。

### 61. 断言"来源端口"前先想清楚那是**谁的**端口

第一版 `uplinkGoesToTheTerminalAddressAndPort` 里写了

```cpp
QCOMPARE(fromPort, terminalPort);   // 错
```

跑出来是 `Compared values are not the same`。想清楚才发现：`readDatagram`
回填的 `fromPort` 是**发送方**（即 `CallSession` 的音频 socket）的端口，也就是
协议端口 `12345`；而 `terminalPort` 是**接收方**（假门口机）的临时端口。
两者本来就该不同，断言写反了。

正确的断言是**两件事分开说**：

- "发对了**目的**端口"由**能收到**本身证明 —— 那个临时端口只有 `terminal`
  在监听，`CallSession` 若把包发去 `12345` 或别处，`terminal` 什么也收不到；
- "来源是会话自己"则断言 `fromPort == kAudioPort`，并顺带断言
  `from.isLoopback()`。

> 教训：**先量再断言**。这个错误不是断言太松，而是把"来源"和"目的"搞混了，
> 静态看代码很难发现，跑一次就暴露。

### 62. 有些变异**就是抓不到** —— 实测确认后写进 `UNDETECTABLE`，别假装覆盖

`verify_call_session_test.py` 里有 5 个退化**实测无判别力**。诚实地记录它们
（而不是留一堆假断言让人以为这块被守住了），并**交给静态规则**
（`check_call_session_contract_is_pinned`）守住意图：

1. **两个口的 `ShareAddress`。** 探针 `result20.txt` A 组，三组对照全部是
   `true / false`：

   ```
   A1 两者都带 ShareAddress : true / false
   A2 第一个独占、第二个共享 : true / false
   A3 第一个共享、第二个独占 : true / false
   ```

   也就是说"能不能重复绑同一端口"取决于**本机 socket 语义**，与共享标志
   无关（Windows 上 `SO_REUSEADDR` 并不允许两个 socket 同时绑同一 UDP 端口）。
   于是测不出差别。**但这属于跨平台行为差异**：Linux 上 `SO_REUSEADDR`
   是允许重复绑的，若将来在 Linux 上跑测试并观察到差异，应立即把它提升为
   真变异。

2. **音频/视频 `readDatagram` 的返回值判断与缩容。** 探针 `result20.txt`
   B 组：对 `0/1/4/100/640/678/1400/65507` 共 8 种长度，返回值**恒等于**
   `pendingDatagramSize()`（不等次数 = 0）。UDP 上不会短读，这两句永不生效。
   与第 31 轮的 `monitor_client` 结论一致。

   > 注意：这段代码**仍然值得留着** —— 它防的是 Qt 实现变化与平台差异
   > （`QByteArray::resize()` 不清零新分配字节，失败时尾部是未初始化内存）。
   > 它属于"防御性但当前不可观测"，**不是死代码**。

3. **上行语音的"未学到地址不发"守卫。** 探针 `result19.txt`：

   ```
   默认 QHostAddress: isNull=true  protocol=-1
   writeDatagram(空地址, 有效端口) 返回 = -1   sink 收到 = 无
   writeDatagram(127.0.0.2, 0)     返回 = 640
   对照 writeDatagram(127.0.0.2, sink端口) 返回 = 640  sink 收到 = 有
   ```

   地址为空时 **Qt 自己就拒绝发送**，所以那道
   `if (!m_deviceAddress.isNull() && m_devicePort != 0)` 与 Qt 内部校验重叠。
   保留它是**可读性 + 显式意图**，不是唯一防线。

夹具里为此单列 `UNDETECTABLE` 段，逐个**确认必须抓不到**；一旦某个竟然被抓
到了，夹具会报错

```
*** 竟然被抓到了（N 条 FAIL, rc=X）
    => 它已可观测，应提升为真变异，而不是继续免责
```

这样"不可观测"这个判断本身也是**被验证过的**，不会随着 Qt 或平台变化而
悄悄变成过期的免责声明。

还补了一个**真能区分**的用例 `startForgetsTheLearnedReturnAddress`：
重复 `start()` 必须先 `stop()`，而 `stop()` 会清掉学到的回传地址。少了那句
`if (m_running) stop();`，新通话**还没听到对方**就会把本地语音发到**上一次
通话的对端地址**去 —— 这是端口本身区分不出来的（自己已绑着 12345 时再绑一次，
无论是否先 `stop()` 都拿不到干净端口）。

### 63. 新加一个**同类**测试目标，会把旧规则的宽松正则变成**假绿**

这是第 34 轮**加测试时才暴露出来**的一个既有规则缺陷，价值超出本轮本身。

`check_serial_light_contract_is_pinned` 里检查影子头必须带 `BEFORE` 的那条正则
原本是：

```python
re.search(r"target_include_directories\s*\(\s*\w+\s+BEFORE\b", cm)
```

它匹配**任意**带 `BEFORE` 的目标。`serial_light` 是当时唯一一个影子头目标，
所以"能匹配上"等价于"serial_light 带了 BEFORE"，规则看着是好的。

第 34 轮新增了 `desktop_test_call_session`，它**也**带 `BEFORE`。于是把
serial_light 那行 `BEFORE` 删掉之后，正则**仍然命中**（命中的是新目标），
规则静默通过 —— `verify_serial_light_rule.py` 的故障注入当场报出

```
CMake 去掉 BEFORE（影子头排在 Qt 之后）  *** 未被抓到（假绿）rc=0
```

**为什么危险：** 这一类"正则匹配了同类结构里的别处"的假绿，不会因为被测
代码变坏而报警。它平时完全沉默，只在有人真的删掉 `BEFORE` 时才失效 ——
而那一刻正是最需要它响的时候。丢掉 `BEFORE` 的后果还很隐蔽：影子头排在 Qt
的 include 之后，`#include <QSerialPort>` / `<QAudioFormat>` 会命中**真 Qt 头**，
测试照样编译、照样通过，只是在测真硬件 —— 换成另一台机器就变脸。

**修法：** 新增 `_cmake_call_containing(text, command, marker)`，先按括号配对
把**包含该影子头目录**的那一次 `target_include_directories(...)` 调用整段框
出来，再**只在这段里**找 `BEFORE`。找不到该调用就报"规则自身需修复"，
而不是假通过。call_session 的同类检查从一开始就用这个函数。

> 教训：**"当前仓库能过"证明不了规则有判别力** —— 只有当同类结构只有一个
> 实例时，宽松正则才**碰巧**等价于精确判断。新增第二个实例就会拆掉这层巧合。
> 所以每加一个同类目标，都要重跑**所有**相关夹具，而不只是新写的那个。
> 本条正是这样被发现的：新夹具跑绿了，旧夹具红了。

### 64. 那 9 行"可达未测"其实是**误分类** —— 钉住前提，而不是留作待办

覆盖率报告把 `call_session.cpp` 的 9 行算作「可达未测」，依据是"所在函数
在生产代码里有调用者"（`coverage_report.py` 的 `member_functions` /
`called_method_names`）。按工具的定义没错，但结论错了：

- L71 `return true;`（`startAudioSocket()` 的 `if (m_audioSocket)` 早返回）
- L94 同上（`startVideoSocket()`）
- L119-121（`startAudioOutput()` 里"先拆旧的输出"）
- L138-140（`startAudioInput()` 里"先拆旧的输入"）

它们真正**不可达**，理由是：`start()` 是这三个函数的唯一调用者；`start()`
在 `m_running` 为真时必定先 `stop()`，而 `stop()` **无条件**把
`m_audioSocket` / `m_videoSocket` / `m_audioOutput` / `m_audioInput` 全部置空；
`m_running` 为假时这些指针本来也是空（构造函数不建任何东西）。

**关键点：** "这 9 行不可达"这个结论**依赖 `stop()` 清空指针这个不变量**。
一旦有人从 `stop()` 里删掉某一行，那些守卫立刻变成**真实可达**的代码路径，
而且很可能是个真 bug（残留的 socket 会带着旧连接进入新通话）。

所以正确做法不是把这 9 行当"待办"永久供着（那既做不完、也不会有人看），
而是把**它们不可达的前提**钉住：规则的第 4 条要求 `stop()` 里四个成员**各自
都有一条无条件的 `member = nullptr;`**。前提破了就响。故障注入分别删掉四个
`if` 块，四个变异全部被抓到。

> 这也是对「可达未测」这一列的**主动清理**：它不只有"没写测试"一种成因，
> 还有"工具口径不够精细"这一种。后者该修正的是**判断依据**，而不是补一个
> 假装能覆盖不可达代码的测试（那种测试只能靠反射/私有点击硬凑，脆弱且无意义）。

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
python3 tools/verify_monitor_client_rule.py
python3 tools/verify_monitor_client_test.py
python3 tools/verify_weather_service_rule.py
python3 tools/verify_weather_service_test.py
python3 tools/verify_serial_light_rule.py
python3 tools/verify_serial_light_test.py
python3 tools/verify_call_session_rule.py
python3 tools/verify_call_session_test.py
bash tools/run_coverage.sh

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
