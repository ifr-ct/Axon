# Axon

**面向 ARM 固件的桌面遥测变量配置工具。** 读取 `.axf` / ELF 的 DWARF 调试信息，按符号路径收藏变量，编排通道并生成小端二进制切换帧。当前为 V1 MVP，应用窗口和可执行文件沿用 **Telemetry Studio** 名称。

Python + pyelftools + pywebview + pyserial 后端配合本地 HTML/CSS/JavaScript 仪表盘；无需前端构建、CDN 或数据库。V1 可生成、复制配置帧，并可通过本机串口或 TCP Client 发送；TCP 下行原始字节可由本机 `127.0.0.1:9000` 代理转发给 VOFA+。UDP 转发尚未接入。

## 功能概览

| 模块 | 当前能力 |
| --- | --- |
| 固件解析 | 后台解析全局/静态变量，展开结构体、类、union 和定长多维数组 |
| 类型与地址 | 7 种协议基础类型及 1 字节 bool，完整宽度 RAM 白名单检查 |
| 变量浏览 | 变量树、路径/类型/地址搜索；仅展开相关分支，名称命中的结构体默认折叠 |
| 通道配置 | 收藏夹、命名预设、拖拽/按钮排序，重编译后按路径匹配最新地址 |
| 协议帧 | CRC-16/MODBUS、小端编码，HEX / C 数组 / Python Bytes 输出 |
| 串口发送 | 本机 COM 口连接/断开与配置帧发送；Mock 仅记录日志 |
| TCP + 本机代理 | 单条 TCP Client 连接车上模块；本机代理把下行原始字节转发给 VOFA+ |
| 多项目 | `.tmws` 工作区、500ms 自动保存、启动恢复及最近 5 个工作区 |
| 桌面分发 | Windows x64 单文件 EXE，无控制台，无需预装 Python |
| 示例模式 | 无固件文件即可体验 16 个示例符号与模拟发送日志 |
| 项目接入助手 | 离线生成固件接入、符号/指纹准备和联调验收提示词，一键复制给客户的 AI 编程助手 |

## 获取源码

```powershell
git clone https://github.com/ifr-ct/Axon.git
cd Axon
```

源代码仓库不包含 `dist/`、虚拟环境、构建缓存、个人 `.tmws` 或真实固件。已有本地 EXE 可直接使用；从 Git 克隆后请按下文运行源码或构建 EXE。

## 目录与核心模块

```text
main.py                       pywebview 窗口 / 回环 HTTP 服务
start.bat                     Windows 一键安装依赖并启动
telemetry/
  parser.py                   后台 ELF/DWARF 解析 + 示例数据
  onboarding.py               项目接入提示词模板与当前协议快照
  protocol.py                 ChannelSlot、CRC16、纯函数编解码
  bridge.py                   UI 动作、后台任务、刷新提示与路径重绑定
  storage.py                  app_state.json / .tmws 校验与原子替换写入
  transports/
    base.py                   统一生命周期与接收回调接口
    mock_transport.py         V1 模拟发送、最多保留 200 条日志
    serial_transport.py       真实串口连接 / 发送（pyserial）
    tcp_client_transport.py   单条 TCP Client 连接 / 发送 / 接收回调
    proxy_server.py           127.0.0.1 本机代理（转发下行字节给 VOFA+）
    tcp_server_transport.py   本地代理旧名称兼容别名
    __init__.py               TransportManager 调度
web/                          HTML、CSS、JavaScript 仪表盘
tests/                        unittest 与程序生成的 ARM ELF 测试数据
requirements.txt              Python 依赖
requirements-build.txt        PyInstaller 构建依赖
TelemetryStudio.spec          单文件 EXE 打包配置（包含 web 资源）
AGENTS.md                     贡献指南
```

## 启动

### Windows 单文件 EXE

直接双击 `dist/TelemetryStudio.exe`，无需 BAT、Python 或虚拟环境。可将 EXE 单独复制到其他文件夹；HTML/CSS/JavaScript、Python 运行时与解析依赖已打包。

目标系统为 Windows x64，仍需系统安装 Microsoft Edge WebView2 Runtime 和 .NET Framework 4.6.2+（通常 Windows 10/11 已有）。工作区记忆仍保存在用户目录 `~/.axf_telemetry/`，不会写入临时解包目录。单文件首次启动会先解包，可能需要数秒。若启动失败，查看 `~/.axf_telemetry/startup.log`。

重新构建 EXE：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm TelemetryStudio.spec
```

构建结果为 `dist/TelemetryStudio.exe`，可单独复制到其他目录。开发环境已有 `.venv` 时可跳过第一条命令。打包不包含用户配置与工作区；在其他电脑使用时需同时复制自己的 `.tmws` 和对应固件，保持相对目录关系。

### 从源码启动

推荐 Windows、Python 3.11+、Microsoft Edge WebView2 Runtime。首次启动需要联网安装 Python 依赖。

```powershell
.\start.bat
```

或手动安装、运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

浏览器开发模式（首次安装最小依赖后运行）：

```powershell
.\.venv\Scripts\python.exe -m pip install pyelftools pyserial
.\.venv\Scripts\python.exe main.py --browser
```

该模式会打开默认浏览器并在终端打印随机分配的回环端口；可选 `--port <port>` 固定端口。原生文件选择和拖入文件路径功能使用桌面模式；浏览器模式请输入本地绝对路径。

服务仅监听 `127.0.0.1`，每次启动生成 API 令牌；关闭桌面窗口或在浏览器服务终端按 Ctrl+C 退出。若桌面运行失败，先使用浏览器模式检查界面，再检查 WebView2 与 .NET 安装情况。

## 使用

1. 点击“加载示例符号”体验 16 个变量（含 bool）；默认预选 4 通道。或浏览/粘贴本地 `.axf` 路径并点击箭头。桌面 WebView2 支持将文件拖入路径框；普通浏览器请粘贴绝对路径。
2. 展开变量树，点击 ☆ 收藏，点击 + 添加通道。搜索支持路径、类型和十六进制地址。大固件界面最多展示匹配结果的前 500 个叶子，请搜索缩小范围。
3. 拖动槽位或使用 ↑/↓ 调序。HEX 按字段着色，可切换 C-Array / Python Bytes，或用黑色快捷按钮复制。
4. 保存通道预设。收藏与预设仅保存符号路径，加载新版固件后自动解析最新地址；失配显示 Missing，阻止生成错误帧。
5. 设置页可调整帧头、最大通道数与 RAM 白名单。所有 RAM 区间采用 `[start, end)`；检查变量完整宽度。越界符号标黄且不能从变量树添加。
6. UI 每 1.2 秒检测文件修改时间及大小；更新提示出现后点击铃铛或侧栏底部刷新。解析在工作线程进行，失败保留上一次有效符号。新固件仍保留原通道路径。
7. 连接页可连接本机串口，或用 TCP Client 连接车上模块；TCP 连接成功后 Local proxy 默认在 `127.0.0.1:9000` 等待 VOFA+。Mock 仅写日志；串口/TCP 写入成功只代表字节离开主机，不代表固件已接收或生效。

### 串口发送

在连接页输入或选择 COM 口，设置波特率和数据位后点击“连接串口”。连接成功后帧区按钮变为“串口发送”，按当前配置帧写入串口；写入失败会自动关闭端口并显示错误，需重新连接。点击“切换到模拟发送”可在无硬件时继续使用 Mock。串口配置随工作区保存在 `.tmws` 的 `transport.serial`，启动或切换工作区时不会自动打开端口。

当前实现只发送，不读取串口响应，也不提供 ACK、自动重连或流控配置；TXD/RXD 接线、电平、波特率和数据位仍需与固件一致。

### TCP 上游与本机代理

TCP Client 连接车上模块，只建立一条上游连接。连接成功后 Local proxy 默认监听 `127.0.0.1:9000`，VOFA+ 连接该地址即可查看波形；也可在代理卡片中单独启动、停止或修改监听端口。代理只把上游收到的原始下行字节广播给本机 VOFA+ 客户端，不解析、不回传、不缓存。

TCP 配置保存在 `.tmws` 的 `transport.tcp`，代理配置保存在 `transport.proxy`；启动或切换工作区不会自动连接、监听。当前没有自动重连、心跳、TLS 或 UDP 转发；TCP 连接失败或代理端口被占用会在连接页显示错误。

## 多项目工作区与启动记忆

右上角工作区切换器显示当前名称与保存状态：绿色为已保存，琥珀色为等待保存，红色为写入失败。菜单提供最近 5 个工作区、新建、打开 `.tmws`、另存为、立即保存及在资源管理器中定位。桌面模式使用原生文件对话框；浏览器模式通过弹窗输入本地文件路径。

- 全局文件为 `~/.axf_telemetry/app_state.json`，只记录 `last_workspace`、最多 5 条去重的 `recent_workspaces` 路径和 `window_size: {width, height}`。
- 默认项目文件为 `~/.axf_telemetry/default.tmws`；首次启动进入内置空工作区，修改后自动创建默认文件。启动时恢复上次项目并后台解析其固件；工作区文件不存在时回退默认项目。损坏文件保留原样，并进入可“另存为”的内存工作区。
- 项目修改在最后一次操作后 **500ms** 自动保存；槽位顺序、收藏、预设、协议参数及固件选择都纳入持久化。切换项目和关闭窗口前立即刷新未保存修改。原文件只读时可通过“另存为”恢复保存。
- `.tmws` 为标准 UTF-8 JSON，使用同目录临时文件、`fsync` 与 `os.replace` 原子替换。固件路径优先相对于 `.tmws` 目录保存，Windows 跨盘符时使用绝对路径；另存为会重新计算相对路径。
- 固件缺失或解析失败时，项目的收藏与当前槽位仍保留，界面提示 Missing。异步解析旧项目的结果不会覆盖新项目。示例模式的符号只存在于内存，重新启动后可再次点击“加载示例符号”。
- 原版 `%LOCALAPPDATA%\TelemetryStudio\settings.json` 保留原样；如有旧收藏，可将其符号路径复制至新 `.tmws` 的相应字段。

示例项目文件（RAM 区间采用半开区间，收藏与槽位仅存路径）：

```json
{
  "schema_version": 1,
  "name": "WheelLeg 调试",
  "axf_path": "build/WheelLeg.axf",
  "mcu_ram_ranges": [[536870912, 537001984], [603979776, 604504064], [805306368, 805601280]],
  "protocol": {"header": "AA55", "max_channels": 12, "crc": "CRC-16/MODBUS"},
  "favorites": ["g_imu.pitch_rad"],
  "presets": {"姿态": ["g_imu.pitch_rad", "g_system.armed"]},
  "active_slots": ["g_imu.pitch_rad", "g_system.armed"],
  "transport": {}
}
```

## AI 项目接入助手

点击顶部“项目接入助手”，选择 **固件接入 / 符号与指纹 / 联调验收**，可补充项目背景、MCU/工具链和计划链路，点击“生成 / 刷新提示词”后预览、一键复制。将提示词粘贴到已打开客户嵌入式工程的 AI 编程助手，指导其依据工程事实完成接入并给出构建和验证步骤。

提示词从当前工作区读取帧头、最大通道数和 RAM 候选区间，并内置固定的协议字段顺序、Cmd/CRC/Type 约束、build stamp 指纹规则、项目勘察表和链接脚本推导 RAM 白名单的要求。提示词明确要求先输出 MCU/RTOS/链路/RAM 事实表并等待确认，未确认前不得实施地址直读；无法确认 RAM 时转入固定通道表等安全回退。

勾选“附带工作区名称、固件标识、RAM 候选区间与通道样例”时会附带符号路径、RAM 候选区间及有效帧中的 RAM 地址；取消勾选可去除这些项目快照，当前协议设置仍保留。RAM 候选区间只用于对照，提示词仍要求从实际链接脚本和 `.map` 重新推导。

该功能完全在本地生成文本，无需 API Key，不自动调用 AI 或上传工程，也不直接修改客户工程。Demo 不提供硬件帧样例，固件解析中或文件已更新时不附带旧帧。预览固定于生成时的快照，协议或固件变化后需要重新生成。V1 已支持本机串口、TCP Client 发送以及 `127.0.0.1:9000` 本机代理；UDP 转发和遥测上行格式仍需独立实现或确认，模板会明确这些边界。

## 线协议

`Header[2] | Cmd=01[1] | Fingerprint LE[4] | N[1] | (Address LE[4], Type[1]) × N | CRC16 LE[2]`

总长 **10 + 5 × N** 字节（4 通道为 30 B）。CRC-16/MODBUS 初值 `0xFFFF`，反射多项式 `0xA001`，覆盖 CRC 之前的所有字节。类型编号依次为 float32、int32、uint32、int16、uint16、int8、uint8（0–6）。**1 字节 bool 显示为 bool，在线协议中复用 uint8（type 6），无需新增下位机枚举。** 不允许空帧、超限通道或越界地址。`decode()` 验证长度、命令、CRC 和槽位。

## 解析边界

支持已链接、32 位、小端 ARM ELF 可执行文件；需要 DWARF 调试信息。扫描具有静态绝对地址 `DW_OP_addr`、位于已分配可写段（包含自定义 RAM 段）的变量，展开结构体、类、union、定长多维数组与 typedef/const/volatile 包装。同名局部静态变量通过作用域、重复编译单元前缀区分；路径随编译单元名变更时需重新绑定。

V1 支持常量成员偏移和单个 `DW_OP_plus_uconst` 偏移表达式，支持 `DW_ATE_boolean` 编码的 1 字节 bool（包括 typedef/const 包装）；指针、bitfield、动态数组、double、动态位置/location list、C++ 虚继承等不支持的叶子会跳过或提示。递归限制 32 层、100000 个叶子。优化可能删除或改变调试变量；推荐保留调试符号并降低优化。固定地址 ROM 符号不作为可发送变量。

指纹仅对符号表中的 `g_telemetry_build_stamp` 字符串计算 CRC32，遇到结尾 NUL 即停止（与固件 `strlen` 一致），不再对整个 AXF 文件计算 CRC32。该符号应位于已初始化、可读取的段中，并确保目标端采用相同的构建标识字节。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check web/app.js
```

测试包含 CRC 标准向量、字段字节序、非法帧、RAM 边界、收藏重绑定、预设、Mock/串口/TCP 发送，以及 TCP 回环代理转发和无需交叉编译器生成的 ARM ELF32/DWARF4 集成夹具。串口测试通过伪造 `serial.Serial` 验证连接、写入、断开和错误路径，不访问真实 COM 口；TCP/代理测试使用临时回环端口。真实 Keil/ARM Compiler 生成物仍需用目标工程验收，尤其是优化后的 C++ 类型和 DWARF 表达式。

当前测试覆盖协议、工作区、ARM ELF 夹具、串口传输、TCP 上游与本机代理，以及接入提示词的自定义协议、Demo/过期帧排除和项目快照开关。Windows 11 x64 / Python 3.14.3 已完成单文件 EXE 窗口启动与 ARM ELF 夹具解析验证。Node.js 仅用于 JavaScript 语法检查，运行桌面程序无需安装 Node.js。

## 常见问题

- **未发现变量**：确认输入为已链接的 ARM ELF32 小端可执行文件，并保留 DWARF 调试信息。优化删除、动态位置与不支持的类型会影响可用变量，详细边界见上文。
- **收藏显示 Missing**：收藏按路径绑定；固件改名、成员删除或编译单元路径变更后，需重新选择变量。
- **帧无法生成**：至少选择 1 个通道，且槽位数量、类型和完整地址范围必须符合当前项目设置。Missing 和 RAM 越界都会阻止生成。
- **工作区保存失败**：查看切换器中的错误信息，检查目录写权限；可通过“另存为”保存到其他位置。
- **串口连接/发送失败**：确认 COM 口未被其他程序占用、波特率和数据位匹配固件；发送失败会自动关闭端口，需重新连接。串口写入成功不等于固件已接收或生效。
- **TCP 连接/代理失败**：确认车上模块已监听目标 host:port；代理端口被占用、上游断开或 VOFA+ 未连接都会显示在连接页。代理只转发已收到的下行字节，不回传、不缓存。
- **EXE 启动失败**：确认系统具备 WebView2 Runtime 和 .NET Framework，查看 `~/.axf_telemetry/startup.log`。无需复制 `.venv` 或 `web/` 到 EXE 旁边。

## 后续扩展与贡献

`BaseTransport` 与 `TransportManager` 已接入真实串口与单条 TCP Client；本机代理把 TCP 下行原始字节转发给 VOFA+。UDP 转发仍为后续方向；V1 不解析遥测上行格式，串口为只写，串口/TCP 写入成功不代表固件已接收或生效。

贡献前请阅读 [AGENTS.md](AGENTS.md)，修改核心逻辑后运行测试。反馈解析问题时，请说明芯片、编译器、优化等级和 DWARF 版本，并提供可公开的最小复现；请勿提交私有固件、个人工作区或凭据。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。第三方依赖遵循其各自许可证。
