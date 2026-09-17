# 洛雪音乐 Open API 控制端

**语言 / Language:** 中文 | [English](README.en.md)

## 🚀 推荐使用 [ofox.ai](https://ofox.io/x/aiv123)

> **一句话**：一个账号直达 GPT-5.5 / Claude 4.8 Opus / Gemini 3.5 Flash 等 **100+** 顶尖模型，首充额外赠 **$3** 额度。

[👉 注册领取](https://ofox.io/x/aiv123) · 全球专线 · 企业级 SLA · 不留存对话

| ⚡️ 极速稳定 | 🧠 模型全 | 🛡️ 隐私安全 |
|:---:|:---:|:---:|
| 全球专线，企业级 SLA | 100+ 模型一号直达 | 不留存任何对话 |

## ☕ 请我喝可乐

开源不易，欢迎赞助支持：  
👉 [爱发电](https://ifdian.net/a/shellsec)

---

轻量 Python 脚本：连洛雪桌面端本地开放 API，切歌、播放暂停、看当前曲、调音量/静音/进度、收藏。电脑可开网页给手机遥控。播放控制用 **Python 3 标准库**；微信扫码二维码需要 `segno`（见 `requirements.txt`，`启动.bat` / `启动.sh` 会尝试安装）。页面和代理都在 `lx_control.py` 里。

<p align="center">
  <img src="docs/screenshots/01-dark-controls.jpg" width="180" alt="深色主题：暂停与音量">
  <img src="docs/screenshots/02-light-lyrics.jpg" width="180" alt="浅色主题：全文歌词">
  <img src="docs/screenshots/03-dark-lyrics.png" width="180" alt="深色主题：全文歌词">
  <img src="docs/screenshots/04-dark-playing.png" width="180" alt="深色主题：播放中">
</p>
<p align="center"><sub>手机网页遥控：深色 / 浅色 / 高对比，支持进度、歌词、音量与切歌。</sub></p>

## 使用场景

### 微信扫码，直接控制电脑上的洛雪

电脑开着洛雪在放歌，手机和电脑连**同一 Wi-Fi**。双击 `lx启动.bat`（macOS / Linux 用 `./lx启动.sh`）后，控制台会打印局域网地址，并画出一张**白底黑码**的二维码。用微信 **扫一扫** 扫这个码，不用装 App、不用手输 IP，就能在手机里切歌、暂停、调音量、看歌词。

<p align="center">
  <img src="docs/screenshots/05-desktop-qr.jpg" width="480" alt="控制台二维码与洛雪桌面端">
</p>

- 扫的是 `http://192.168.x.x:23333`，**不要扫** `127.0.0.1`（那是电脑自己访问用的）。
- 控制台字体把码扫花时，打开同目录的 `remote-qr.png` 再扫。
- 手机打不开：同一 Wi-Fi，防火墙放行 **TCP 23333**。

同一台电脑上也可以用命令行 REPL 切歌；Windows 可用 `--keys` 单键控制。详细步骤见下方「手机网页遥控」。

> **本机 `--web` / `lx启动.bat` 可自动开启开放 API。** 官方洛雪没有命令行开关。脚本在本机自动拉起桌面端（当时没在运行）时，会先把配置里的 `openAPI.enable` 写成 `true`。已在运行时需重启或手动勾选。详见下方「洛雪里怎么开 API」。

官方文档：<https://lyswhut.github.io/lx-music-doc/desktop/open-api>（**v2.7.0+**；不保证更早的桌面端。）

## 洛雪里怎么开 API

官方桌面端**没有**命令行参数可启用开放 API。本机用 `--web` / `lx启动.bat` 时，若开放 API 还没起来、且洛雪当时**没在运行**，脚本会在自动启动前写入配置：

- 把 `setting["openAPI.enable"]` 写成 `true`
- 配置文件：便携版为 `安装目录/portable/userData/LxDatas/config_v2.json`；否则为 `%APPDATA%\lx-music-desktop\LxDatas\config_v2.json`（macOS：`~/Library/Application Support/lx-music-desktop/LxDatas/config_v2.json`；Linux：`~/.config/lx-music-desktop/LxDatas/config_v2.json`）
- 已有端口会保留；配置里没有端口时默认 `23330`
- **不会**自动勾选「允许来自局域网的访问」（`bindLan`）。本机网页遥控一般不需要；跨设备才要自己勾

若洛雪**已经在运行**，改配置不会立刻生效，需要重启桌面端，或按下面步骤在设置里手动勾选。不想自动启动桌面端时用 `--no-launch`。

想自己勾选时：

1. 打开 **洛雪音乐桌面端**（需 **v2.7.0** 及以上）。
2. **设置 → 开放 API**。
3. 勾选 **启用开放 API 服务**。
4. **服务端口** 保持 `23330`（或改完后，启动脚本时用 `--port` / `LX_API_PORT` 对齐）。
5. 若要从**另一台电脑/本机局域网 IP** 控制，必须勾选 **允许来自局域网的访问**。  
   不勾时服务只绑 `127.0.0.1`，`192.168.x.x` 会连不上。
6. 设置页里的 **服务地址** 会列出本机回环和局域网 IP，用列表里的地址即可。

官方开放 API **没有密码 / token**。  
401 Forbidden 在源码里是「未知路径」的默认回应，不是缺密钥。只有你自己前面加了反代/网关时，才需要 `--token` 或环境变量 `LX_API_TOKEN`。

跨域：服务已返回 `Access-Control-Allow-Origin: *`。浏览器网页可以跨域调；本脚本是本机 Python，不受 CORS 影响。

协议：只有 **HTTP GET**。实时状态用 **SSE**（`/subscribe-player-status`），**没有 WebSocket**。本脚本用短请求控制切歌，不连 SSE。

## 手机网页遥控（推荐）

电脑和手机连**同一 Wi-Fi / 局域网**。对应系统的**洛雪桌面端**需要已安装。本机 `--web` 自动启动时可写入开放 API 开关（见「洛雪里怎么开 API」）；也可以在 **设置 → 开放 API** 里手动勾选。

`--web` / `启动.bat` 时：若本机开放 API 还没起来，脚本会尝试启动洛雪桌面端（已在运行则不再开一份），最多等约 40 秒。本机自动启动前会写入开放 API 开关（见「洛雪里怎么开 API」）。脚本可放在安装目录或其子目录（例如 `D:\Program Files\lx-music-desktop\lxpy`），会向上查找 `lx-music-desktop.exe`。找不到时，可设环境变量 `LX_APP`，或 `--lx-exe`，或在 `lx_remote_state.json` 写入 `"lxExe"`。不想自动启动：`--no-launch`。命令行 REPL / `--keys` 不会自动开洛雪。

| 系统 | 怎么启动 |
| --- | --- |
| Windows | 双击 `启动.bat` |
| macOS / Linux | `chmod +x 启动.sh`（只需一次），再 `./启动.sh` |

或任意系统：

```bash
python3 lx_control.py --web
```

服务监听 `0.0.0.0:23333`，控制台会打印「本机」和「手机」地址，并画出**白底黑码**的局域网二维码（`http://192.168.x.x:23333`，不是 127.0.0.1）。用**微信扫一扫**扫控制台即可。控制台字体把码扫花时，再手动打开同目录的 `remote-qr.png`（不会自动弹窗）。扫不开：手机和电脑同一 Wi-Fi，防火墙放行 **TCP 23333**。

页面只打 23333，由**跑脚本的这台电脑**代理到洛雪 Open API，手机不用直连 23330。

- **洛雪和脚本在同一台电脑**（`--web` / `启动.bat` / `启动.sh` 未指定主机时默认如此）：代理 `127.0.0.1:23330`，不必勾选「允许来自局域网的访问」。本机 API 若只通回环，脚本会自动改走 `127.0.0.1`。
- **洛雪在另一台电脑**：把 `LX_API_HOST` / `--host` 改成洛雪那台的 IP，并勾选 **允许来自局域网的访问**。连的不是本机时，**不会**自动启动桌面端。

```bash
# 本机洛雪
python3 lx_control.py --web --host 127.0.0.1

# 局域网上另一台洛雪
LX_API_HOST=192.168.31.169 python3 lx_control.py --web
```

右上角可点 **深色 / 浅色 / 高对比** 切换风格，选过的会记在手机浏览器里。曲目区显示当前歌词（有翻译/罗马音会多一行），点 **全文歌词** 可展开 LRC，点某一句会跳到对应进度。遥控页只做当前曲控制，没有搜歌、歌单、排行榜入口。

还需要：

1. 该系统已安装 **Python 3**（`python3` 或 `python` / Windows 的 `py -3`）。首次画二维码需要 `pip install -r requirements.txt`（启动脚本会试着装）。
2. 防火墙放行 **TCP 23333**（Windows 首次可能弹窗；macOS「系统设置 → 网络 / 防火墙」；Linux 视发行版打开对应端口）。洛雪自己的 23330 要能被脚本所在机器访问。
3. 不要用流量/访客 Wi-Fi 隔离网络，否则手机摸不到电脑。微信必须扫局域网地址，不要扫 127.0.0.1。

网页端口可改：`--web-port 23333` 或环境变量 `LX_WEB_PORT`。

命令行 REPL：`python3 lx_control.py`（不要加 `--web`）。`--keys` 单键热键只在 Windows 可用，其它系统会退回普通 REPL。

## 命令行怎么用

在本目录：

```bash
python lx_control.py
```

未指定时默认连接 `http://192.168.31.169:23330`（可用 `--host 127.0.0.1` 连本机洛雪）。启动后会先读一次 `/status`，然后进入 REPL：

```
> n          # 下一曲
> p          # 上一曲
> play       # 播放
> pause      # 暂停
> t          # 按当前状态切换播放/暂停
> s          # 当前曲目（含音量）
> vol        # 看当前音量/是否静音
> vol 50     # 音量设为 50（0-100）
> vol +10    # 相对当前音量 +10
> mute       # 静音
> unmute     # 取消静音
> seek 30    # 跳到 30 秒
> seek 1:20  # 跳到 1 分 20 秒
> collect    # 收藏当前曲
> lyric      # 当前 LRC
> lyric-all  # 全部歌词 JSON
> help
> quit
```

单次命令（不进入交互）：

```bash
python lx_control.py next
python lx_control.py status
python lx_control.py volume
python lx_control.py volume 50
python lx_control.py mute
python lx_control.py unmute
python lx_control.py seek 30
```

## 音量怎么用

官方是 `GET /volume?volume=0-100`（文档写 1-100，源码允许 0）。当前音量不在默认 `/status` 里，脚本会带 `filter=...volume,mute,collect`。

```bash
python lx_control.py volume          # 只读，不改音量
python lx_control.py volume 80       # 设为 80
python lx_control.py volume +10      # 在当前基础上 +10
python lx_control.py mute            # GET /mute?mute=true
python lx_control.py unmute          # GET /mute?mute=false
```

REPL 里同样：`vol`、`vol 50`、`mute` / `unmute`。`status` 也会带上「音量 100」等字段。

官方 **没有** 播放模式（循环/随机）、播放列表接口。那些只能在洛雪窗口里操作。

覆盖地址：

```bash
python lx_control.py --host 127.0.0.1 --port 23330 status
python lx_control.py --url http://192.168.31.169:23330 next
```

环境变量（命令行优先）：

| 变量 | 含义 |
| --- | --- |
| `LX_API_HOST` | 洛雪 Open API 主机。命令行默认 `192.168.31.169`；`--web` / `启动.bat` / `启动.sh` 未指定时默认 `127.0.0.1` |
| `LX_API_PORT` | 端口，默认 `23330` |
| `LX_API_URL` | 完整基址，设置后覆盖 host/port |
| `LX_API_TOKEN` | 可选。官方 API 不需要 |
| `LX_WEB_PORT` | 网页端口，默认 `23333` |
| `LX_WEB_BIND` | 网页监听地址，默认 `0.0.0.0` |
| `LX_APP` / `LX_EXE` | 洛雪桌面端 exe / `.app` 路径，找不到安装目录时用 |
| `LX_APP_WAIT` | 自动启动后等待开放 API 的秒数，默认 40 |

Windows 下可单键切歌（不用回车）：

```bash
python lx_control.py --keys
```

`n` 下一曲，`p` 上一曲，空格播放/暂停，`s` 当前曲，`q` 退出。

## API 路径（本脚本用到的）

官方控制接口全部是 **GET**，不是 `play-next` / `play-prev`。

| 动作 | 路径 | 脚本命令 |
| --- | --- | --- |
| 当前曲目/状态 | `GET /status` | `status` |
| 下一曲 | `GET /skip-next` | `next` |
| 上一曲 | `GET /skip-prev` | `prev` |
| 播放 / 暂停 | `GET /play`、`GET /pause` | `play` / `pause` / `toggle` |
| 当前 LRC | `GET /lyric` | `lyric` |
| 全部歌词 | `GET /lyric-all` | `lyric-all` |
| 音量 | `GET /volume?volume=0-100` | `volume` / `volume 50` |
| 静音 | `GET /mute?mute=true\|false` | `mute` / `unmute` |
| 进度 | `GET /seek?offset=秒` | `seek 30` |
| 收藏/取消 | `GET /collect`、`GET /uncollect` | `collect` / `uncollect` |
| 实时状态（SSE） | `GET /subscribe-player-status` | 不做 |

REPL 里 `next` / `play-next` 都会打到 `/skip-next`。官方没有播放模式、歌单列表接口。

## 常见错误

| 现象 | 原因与处理 |
| --- | --- |
| 手机打不开网页 | 电脑没开 `--web`、不是同一 Wi-Fi、防火墙拦了 **23333** |
| 微信扫码进不去 | 扫的应是 `http://电脑局域网IP:23333`；可改扫 `remote-qr.png`；检查防火墙 23333 |
| 网页能开但显示连不上洛雪 | 洛雪没开、端口不对，或脚本连的不是洛雪那台（本机用 `127.0.0.1`，跨设备要勾「允许来自局域网的访问」） |
| 提示未找到洛雪桌面端 | 安装洛雪后重试；或设 `LX_APP` / `--lx-exe` 指向 `lx-music-desktop.exe` |
| 进程已在运行但 API 连不上 | 已在运行时无法热启用 API：请勾选 **设置 → 开放 API → 启用**，或退出洛雪后再用 `--web` / `启动.bat` 让脚本启动前写入配置 |
| 连接被拒绝 / 超时 / 连不上 | 洛雪没开、没勾「允许来自局域网的访问」、IP/端口不对、防火墙拦了 23330 |
| 只能 `127.0.0.1` 通、局域网 IP 不通 | 未勾选 **允许来自局域网的访问**（否则只监听 127.0.0.1） |
| HTTP 401 Forbidden | 路径写错（例如 `/play-next`）。官方无密钥；自建网关才查 token |
| HTTP 400 | `seek` / `volume` / `mute` 参数不合法 |
| 能通但切歌没反应 | API 已开，但播放器里没有下一首/上一首可切 |
| 浏览器跨域失败 | 旧版本在加 CORS 之前；升级到支持跨域的版本，或用本脚本绕过浏览器 |

Windows 若 `python` 不可用，用 `py -3 lx_control.py`。macOS / Linux 一般是 `python3`。
