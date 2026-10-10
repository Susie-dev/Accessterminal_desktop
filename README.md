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

```sh
cmake -S . -B build -DACCESSTERMINAL_BUILD_TESTS=ON
cmake --build build && ctest --test-dir build --output-on-failure
```

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

---

## 关键约定（由自动化检查强制）

以下六条是本工程最容易在重构中被悄悄破坏、又最难靠运行测试发现的约定。
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

用 `.clang-format` 统一格式，但**格式不是正确性**——上述六条请以
`verify.py` 的结果为准。

---

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
