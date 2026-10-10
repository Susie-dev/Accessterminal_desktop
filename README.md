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
