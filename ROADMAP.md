# Axon Roadmap

## V1 收尾

- [x] 品牌与命名统一：窗口 `Axon`、`Axon.spec`、`dist/Axon.exe`、工作区 `.axon`。
- [x] `.tmws` 向下兼容读取；旧工作区打开后仍写回原路径，新建/另存为使用 `.axon`。
- [x] 移除 `tcp_server_transport.py` 旧名称文件，本机代理统一由 `proxy_server.py` 提供。
- [x] 工作区 Schema 预留可选 `writable_ram_ranges`；与只读 `mcu_ram_ranges` 分离，V1 不参与帧生成。
- [x] 串口读线程捕获 `SerialException` / `OSError`，断线后回传错误状态；连接页保留“刷新端口”。
- [x] `.axf` 后台 mtime/size 轮询；自动弹出更新/忽略提示，确认已烧录后重解析并重绑定符号地址；文件缺失/解析失败后自动重新等待下一次变化。
- [x] 本机代理同时服务串口与 TCP 下游原始字节。

## 技术栈结论

| 模块 | 结论 | 后续路线 |
| --- | --- | --- |
| `web/` | 保留原生 HTML/CSS/JS | 仅在变量树超过 1 万节点卡顿时增加轻量虚拟列表，不引入 React/Vue |
| `storage.py` | 保留 JSON + 原子替换 | 继续随 Git 流转；新增字段保持可选、向后兼容 |
| `parser.py` | 继续使用 pyelftools | 先做懒解析或按文件哈希缓存；大工程仍慢时再评估 Rust `object` + `gimli` 扩展 |
| 打包 | 当前 PyInstaller 单文件 | 评估 PyInstaller `--onedir` 或 Nuitka，优先改善冷启动与 Defender 误报 |
| 桌面/通信 | 保留 pywebview + 回环 HTTP + pyserial | 高频数据面继续留在 Python 后端直通代理；前端只拉取节流后的统计；需要实时波形/1 kHz 录波时再评估 Tauri 2.0 |

## V2

- **P1 JustFloat + 帧解包器**：原始字节仍零延迟直通 VOFA+；后端旁路解析 `(ts_ms, float[])` 结构化数据，新增 `telemetry/stream.py`。
- **P2 CSV 记录 + 条件触发**：新增 `telemetry/recorder.py`、`telemetry/trigger.py`，共用带真实变量名的 CSV 写入器，覆盖常态录波与故障黑匣子。
- **P3 枚举与位域解析**：离线提取 DWARF 枚举/位域元数据，在监视视图显示状态名和标志位。
- **P4 受控调参**：先固定写协议、ACK、工作区 Schema 与 MCU 写白名单，再实现 RAM 在线写入；写白名单继续与只读白名单分离。

## 边界

- 不擅自增加 ACK、采样率、N=0 或上行格式；相关语义必须先与固件确认。
- 当前代理只转发原始字节，不解析、不缓存、不回传。
- 通用接入提示词继续要求“先勘察、再从链接脚本推导 RAM 白名单”，无法确认时使用固定通道表等安全回退。
