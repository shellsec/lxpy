#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""洛雪音乐桌面端 Open API 轻量控制端（仅标准库）。"""

from __future__ import print_function

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

DEFAULT_HOST = "192.168.31.169"
DEFAULT_PORT = 23330
DEFAULT_TIMEOUT = 5.0
DEFAULT_WEB_PORT = 23333
DEFAULT_WEB_BIND = "0.0.0.0"
PAGE_VER = "0917j"
DEFAULT_LAUNCH_WAIT = 40.0
_WIN_CREATE_NO_WINDOW = 0x08000000
_WIN_DETACHED = 0x00000008
_WIN_NEW_GROUP = 0x00000200
# 默认 /status 不含 volume/mute/collect，要自己带 filter
STATUS_FILTER = (
    "status,name,singer,albumName,lyricLineText,lyricLineAllText,"
    "duration,progress,playbackRate,volume,mute,collect,picUrl"
)


def _configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

# 官方文档没有 play-next / play-prev，切歌路径是 skip-*
ALIASES = {
    "n": "next",
    "next": "next",
    "skip-next": "next",
    "play-next": "next",
    "p": "prev",
    "prev": "prev",
    "skip-prev": "prev",
    "play-prev": "prev",
    "play": "play",
    "pause": "pause",
    "toggle": "toggle",
    "t": "toggle",
    "s": "status",
    "status": "status",
    "now": "status",
    "lyric": "lyric",
    "l": "lyric",
    "lyric-all": "lyric-all",
    "lyrics": "lyric-all",
    "la": "lyric-all",
    "volume": "volume",
    "vol": "volume",
    "v": "volume",
    "mute": "mute",
    "unmute": "unmute",
    "seek": "seek",
    "collect": "collect",
    "like": "collect",
    "uncollect": "uncollect",
    "unlike": "uncollect",
    "h": "help",
    "help": "help",
    "?": "help",
    "q": "quit",
    "quit": "quit",
    "exit": "exit",
}


def env_or(name, default):
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _state_path():
    return os.path.join(_script_dir(), "lx_remote_state.json")


def load_state():
    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(updates):
    data = load_state()
    data.update(updates)
    try:
        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except Exception:
        pass


def load_loop_state():
    return bool(load_state().get("loopOne"))


def save_loop_state(flag):
    save_state({"loopOne": bool(flag)})


def song_key_of(data):
    if not data:
        return ""
    return "{}|{}".format(data.get("name") or "", data.get("singer") or "")


def set_loop_one(server, flag):
    server.lx_loop_one = bool(flag)
    save_loop_state(server.lx_loop_one)


def mark_user_skip(server):
    server.lx_loop_skip_until = time.time() + 3.0
    server.lx_loop_song = None


def _loop_tick(server):
    if getattr(server, "lx_loop_busy", False):
        return
    data = get_status(server.lx_base, server.lx_token, server.lx_timeout)
    key = song_key_of(data)
    status = data.get("status") or ""
    try:
        progress = float(data.get("progress") or 0)
        duration = float(data.get("duration") or 0)
        rate = float(data.get("playbackRate") or 1) or 1
    except (TypeError, ValueError):
        return

    now = time.time()
    skip_grace = now < float(getattr(server, "lx_loop_skip_until", 0) or 0)
    prev_key = getattr(server, "lx_loop_song", None)
    prev_prog = float(getattr(server, "lx_loop_prog", 0) or 0)
    prev_dur = float(getattr(server, "lx_loop_dur", 0) or 0)
    last_rewind = float(getattr(server, "lx_loop_rewind_at", 0) or 0)

    if key and prev_key and key != prev_key:
        if skip_grace:
            server.lx_loop_song = key
            server.lx_loop_prog = progress
            server.lx_loop_dur = duration
            return
        near_end = prev_dur > 1 and prev_prog >= prev_dur - 2.8
        if near_end and now - last_rewind > 1.8:
            server.lx_loop_busy = True
            try:
                do_control(
                    server.lx_base, "/skip-prev", server.lx_token, server.lx_timeout, after_status=False
                )
                do_control(
                    server.lx_base,
                    "/seek",
                    server.lx_token,
                    server.lx_timeout,
                    after_status=False,
                    query={"offset": "0"},
                )
                do_control(
                    server.lx_base, "/play", server.lx_token, server.lx_timeout, after_status=False
                )
                server.lx_loop_rewind_at = time.time()
                server.lx_loop_song = prev_key
                server.lx_loop_prog = 0
            finally:
                server.lx_loop_busy = False
            return
        server.lx_loop_song = key
        server.lx_loop_prog = progress
        server.lx_loop_dur = duration
        return

    server.lx_loop_song = key or prev_key
    server.lx_loop_prog = progress
    server.lx_loop_dur = duration

    if now - last_rewind < 1.2:
        return

    if status == "stoped" and duration > 1 and progress >= max(0.0, duration - 0.8):
        server.lx_loop_busy = True
        try:
            do_control(
                server.lx_base,
                "/seek",
                server.lx_token,
                server.lx_timeout,
                after_status=False,
                query={"offset": "0"},
            )
            do_control(server.lx_base, "/play", server.lx_token, server.lx_timeout, after_status=False)
            server.lx_loop_rewind_at = time.time()
            server.lx_loop_prog = 0
        finally:
            server.lx_loop_busy = False
        return

    if status != "playing":
        return

    lead = max(0.65, 0.5 * rate + 0.3)
    if duration > 2 and progress >= duration - lead:
        server.lx_loop_busy = True
        try:
            do_control(
                server.lx_base,
                "/seek",
                server.lx_token,
                server.lx_timeout,
                after_status=False,
                query={"offset": "0"},
            )
            server.lx_loop_rewind_at = time.time()
            server.lx_loop_prog = 0
        finally:
            server.lx_loop_busy = False


def start_loop_watch(server):
    server.lx_loop_one = load_loop_state()
    server.lx_loop_stop = False
    server.lx_loop_busy = False
    server.lx_loop_song = None
    server.lx_loop_prog = 0.0
    server.lx_loop_dur = 0.0
    server.lx_loop_skip_until = 0.0
    server.lx_loop_rewind_at = 0.0

    def run():
        while not getattr(server, "lx_loop_stop", False):
            try:
                if getattr(server, "lx_loop_one", False):
                    _loop_tick(server)
                    time.sleep(0.35)
                else:
                    time.sleep(0.8)
            except Exception:
                time.sleep(1.2)

    thread = threading.Thread(target=run, name="lx-loop-one", daemon=True)
    thread.start()
    server.lx_loop_thread = thread


def build_base_url(args):
    if args.url:
        return args.url.rstrip("/")
    env_url = env_or("LX_API_URL", "")
    if env_url:
        return env_url.rstrip("/")
    host = args.host or env_or("LX_API_HOST", DEFAULT_HOST)
    port = args.port if args.port is not None else int(env_or("LX_API_PORT", DEFAULT_PORT))
    return "http://{}:{}".format(host, port)


def request(base_url, path, token=None, timeout=DEFAULT_TIMEOUT, query=None):
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Accept": "application/json, text/plain;q=0.9, */*;q=0.8"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["X-Api-Key"] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            text = raw.decode("utf-8", errors="replace")
            return resp.status, ctype, text
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        text = raw.decode("utf-8", errors="replace") if raw else str(exc)
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", text


def explain_error(exc, base_url):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return (
                "HTTP 401：官方开放 API 对未知路径会回 Forbidden；"
                "若路径正确仍 401，再检查是否有反代/自建网关要求密钥。"
            )
        return "HTTP {}：{}".format(exc.code, exc.reason)
    reason = getattr(exc, "reason", exc)
    name = type(reason).__name__ if reason is not exc else type(exc).__name__
    hint = (
        "连不上 {}。请确认：1) 洛雪已开「启用开放 API 服务」；"
        "2) 跨设备时勾选「允许来自局域网的访问」；"
        "3) 端口/IP 一致且防火墙放行。"
    ).format(base_url)
    return "{}（{}）：{}".format(name, reason, hint)


def call(base_url, path, token=None, timeout=DEFAULT_TIMEOUT, query=None):
    try:
        return request(base_url, path, token=token, timeout=timeout, query=query)
    except Exception as exc:
        raise RuntimeError(explain_error(exc, base_url))


def parse_status_body(text):
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def format_status(data):
    if not data:
        return "(无状态数据)"
    status = data.get("status") or "?"
    name = data.get("name") or "未知曲目"
    singer = data.get("singer") or ""
    album = data.get("albumName") or ""
    line = data.get("lyricLineText") or ""
    title = " - ".join(part for part in (name, singer) if part)
    extra = []
    if album:
        extra.append(album)
    progress = data.get("progress")
    duration = data.get("duration")
    if progress is not None and duration:
        extra.append("{:.0f}/{:.0f}s".format(float(progress), float(duration)))
    if data.get("volume") is not None:
        extra.append("音量 {}".format(data.get("volume")))
    if data.get("mute") is True:
        extra.append("已静音")
    if data.get("collect") is True:
        extra.append("已收藏")
    suffix = " | ".join(extra)
    text = "[{}] {}".format(status, title)
    if suffix:
        text += "  ({})".format(suffix)
    if line:
        text += "\n  歌词：{}".format(line)
    return text


def format_volume(data):
    if not data:
        return "音量：未知"
    vol = data.get("volume")
    mute = data.get("mute")
    mute_text = "是" if mute is True else ("否" if mute is False else "?")
    return "音量 {}  静音：{}".format(vol if vol is not None else "?", mute_text)


def get_status(base_url, token, timeout):
    code, _, text = call(
        base_url, "/status", token=token, timeout=timeout, query={"filter": STATUS_FILTER}
    )
    if code != 200:
        raise RuntimeError("读取当前曲目失败 HTTP {}：{}".format(code, text[:300]))
    data = parse_status_body(text)
    if data is None:
        raise RuntimeError("状态接口返回的不是 JSON：{}".format(text[:300]))
    return data


def do_control(base_url, path, token, timeout, after_status=True, query=None):
    code, _, text = call(base_url, path, token=token, timeout=timeout, query=query)
    if code != 200:
        raise RuntimeError("调用 {} 失败 HTTP {}：{}".format(path, code, text[:300]))
    ok = (text or "OK").strip()
    if after_status:
        try:
            return ok, get_status(base_url, token, timeout)
        except Exception:
            return ok, None
    return ok, None


def parse_volume_arg(raw, current=None):
    text = raw.strip()
    if text.startswith(("+", "-")) and text[1:].isdigit():
        if current is None:
            raise RuntimeError("无法读取当前音量，不能用相对调节")
        value = int(round(float(current))) + int(text)
    elif text.isdigit():
        value = int(text)
    else:
        raise RuntimeError("音量请用 0-100，或 +10 / -10")
    value = max(0, min(100, value))
    return value


def parse_seek_arg(raw):
    text = raw.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].replace(".", "", 1).isdigit():
            raise RuntimeError("进度请用秒数，如 30，或 1:20")
        return int(parts[0]) * 60 + float(parts[1])
    try:
        offset = float(text)
    except ValueError:
        raise RuntimeError("进度请用秒数，如 30，或 1:20")
    if offset < 0:
        raise RuntimeError("进度不能为负数")
    return offset


def print_help():
    print(
        "命令：\n"
        "  n / next / skip-next     下一曲\n"
        "  p / prev / skip-prev     上一曲\n"
        "  play                     播放\n"
        "  pause                    暂停\n"
        "  t / toggle               播放/暂停切换\n"
        "  s / status / now         当前曲目（含音量）\n"
        "  vol / volume             看音量；vol 50 设置；vol +10 / -10 相对调节\n"
        "  mute / unmute            静音 / 取消静音\n"
        "  seek 30 / seek 1:20      跳到指定秒\n"
        "  collect / uncollect      收藏 / 取消收藏\n"
        "  l / lyric                当前 LRC\n"
        "  lyric-all                全部歌词 JSON\n"
        "  h / help                 帮助\n"
        "  q / quit                 退出\n"
        "单次调用：python lx_control.py volume\n"
        "          python lx_control.py volume 50\n"
        "          python lx_control.py seek 30"
    )


def run_command(cmd, base_url, token, timeout, args=None):
    args = list(args or [])
    if cmd == "help":
        print_help()
        return True
    if cmd in ("quit", "exit"):
        return False
    if cmd == "status":
        print(format_status(get_status(base_url, token, timeout)))
        return True
    if cmd == "lyric":
        code, _, text = call(base_url, "/lyric", token=token, timeout=timeout)
        if code != 200:
            raise RuntimeError("读取歌词失败 HTTP {}：{}".format(code, text[:300]))
        print(text or "(空歌词)")
        return True
    if cmd == "lyric-all":
        code, _, text = call(base_url, "/lyric-all", token=token, timeout=timeout)
        if code != 200:
            raise RuntimeError("读取全部歌词失败 HTTP {}：{}".format(code, text[:300]))
        data = parse_status_body(text)
        print(json.dumps(data, ensure_ascii=False, indent=2) if data else (text or "(空)"))
        return True
    if cmd == "volume":
        if not args:
            print(format_volume(get_status(base_url, token, timeout)))
            return True
        current = get_status(base_url, token, timeout).get("volume")
        value = parse_volume_arg(args[0], current)
        ok, status = do_control(
            base_url, "/volume", token, timeout, query={"volume": str(value)}
        )
        print("/volume?volume={} {}".format(value, ok))
        print(format_volume(status) if status else format_volume({"volume": value}))
        return True
    if cmd in ("mute", "unmute"):
        if cmd == "unmute" or (args and args[0].lower() in ("off", "false", "0")):
            flag = "false"
        elif args and args[0].lower() in ("on", "true", "1"):
            flag = "true"
        elif cmd == "mute" and not args:
            flag = "true"
        else:
            raise RuntimeError("静音用法：mute / unmute / mute on / mute off")
        ok, status = do_control(
            base_url, "/mute", token, timeout, query={"mute": flag}
        )
        print("/mute?mute={} {}".format(flag, ok))
        print(format_volume(status) if status else "")
        return True
    if cmd == "seek":
        if not args:
            raise RuntimeError("用法：seek 30  或  seek 1:20")
        offset = parse_seek_arg(args[0])
        ok, status = do_control(
            base_url, "/seek", token, timeout, query={"offset": "{:.3f}".format(offset)}
        )
        print("/seek?offset={:.3f} {}".format(offset, ok))
        if status:
            print(format_status(status))
        return True
    if cmd == "toggle":
        data = get_status(base_url, token, timeout)
        path = "/pause" if data.get("status") == "playing" else "/play"
        ok, status = do_control(base_url, path, token, timeout)
        print("{} {}".format(path, ok))
        if status:
            print(format_status(status))
        return True

    path_map = {
        "next": "/skip-next",
        "prev": "/skip-prev",
        "play": "/play",
        "pause": "/pause",
        "collect": "/collect",
        "uncollect": "/uncollect",
    }
    path = path_map[cmd]
    ok, status = do_control(base_url, path, token, timeout)
    print("{} {}".format(path, ok))
    if status:
        print(format_status(status))
    return True


def health_check(base_url, token, timeout):
    try:
        data = get_status(base_url, token, timeout)
    except Exception as exc:
        print("健康检查失败：{}".format(exc), file=sys.stderr)
        return False
    print("已连接 {}  当前：{}".format(base_url, format_status(data).split("\n", 1)[0]))
    return True


def repl(base_url, token, timeout):
    print("洛雪控制  {}   输入 help 看命令，quit 退出".format(base_url))
    health_check(base_url, token, timeout)
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not raw:
            continue
        parts = raw.split()
        key = ALIASES.get(parts[0].lower())
        if not key:
            print("未知命令：{}（输入 help）".format(raw))
            continue
        try:
            if not run_command(key, base_url, token, timeout, args=parts[1:]):
                return
        except Exception as exc:
            print(exc, file=sys.stderr)


def hotkeys(base_url, token, timeout):
    try:
        import msvcrt
    except ImportError:
        print("当前系统没有 msvcrt，改用普通 REPL。", file=sys.stderr)
        repl(base_url, token, timeout)
        return
    print("热键模式  {}   [n]下一曲 [p]上一曲 [空格]播放/暂停 [s]当前 [l]歌词 [h]帮助 [q]退出".format(base_url))
    health_check(base_url, token, timeout)
    mapping = {
        b"n": "next",
        b"p": "prev",
        b" ": "toggle",
        b"s": "status",
        b"l": "lyric",
        b"h": "help",
        b"q": "quit",
    }
    while True:
        ch = msvcrt.getch()
        if ch in (b"\x03", b"\x1a"):
            print()
            return
        cmd = mapping.get(ch.lower() if isinstance(ch, bytes) else ch)
        if not cmd:
            continue
        print(ch.decode("ascii", errors="replace") if ch.strip() else "space")
        try:
            if not run_command(cmd, base_url, token, timeout):
                return
        except Exception as exc:
            print(exc, file=sys.stderr)


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#1a1410">
<meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<title>洛雪遥控</title>
<style>
:root, [data-theme="dark"] {
  --bg: #1a1410;
  --panel: #261c16;
  --ink: #f6ead6;
  --dim: #b9a48a;
  --line: #3d2e24;
  --copper: #d4894a;
  --go: #c9a46a;
  --play-ink: #1a1410;
  --track: #3f3128;
  --press: #32261e;
  --hint: #8d7763;
  --banner-bg: #3a1f1a;
  --banner-ink: #f3c7bd;
  --state-line: #6d5334;
}
[data-theme="light"] {
  --bg: #f3eee6;
  --panel: #fffaf3;
  --ink: #2a2118;
  --dim: #6d5d4d;
  --line: #d9cbb8;
  --copper: #b56a2b;
  --go: #2f7a4a;
  --play-ink: #fffaf3;
  --track: #d7c8b4;
  --press: #eee4d6;
  --hint: #8a7764;
  --banner-bg: #f4d7cf;
  --banner-ink: #7a2e22;
  --state-line: #9cbc9a;
}
[data-theme="hi"] {
  --bg: #000000;
  --panel: #000000;
  --ink: #ffffff;
  --dim: #ffe566;
  --line: #ffffff;
  --copper: #ffe000;
  --go: #00ff6a;
  --play-ink: #000000;
  --track: #555555;
  --press: #222222;
  --hint: #ffe566;
  --banner-bg: #3a0000;
  --banner-ink: #ffffff;
  --state-line: #00ff6a;
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--ink); }
body {
  font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  padding: calc(16px + env(safe-area-inset-top)) 18px calc(24px + env(safe-area-inset-bottom));
}
.wrap { max-width: 440px; margin: 0 auto; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; }
.brand { font-size: 13px; letter-spacing: .18em; color: var(--copper); flex: 0 0 auto; }
.brand .ver { letter-spacing: 0; font-size: 11px; color: var(--hint); margin-left: 6px; }
.themes { display: flex; gap: 6px; }
.themes button {
  min-height: 40px; padding: 0 10px; border-radius: 12px; font-size: 13px;
}
.themes button.picked { background: var(--copper); color: var(--play-ink); border-color: var(--copper); }
#banner {
  display: none; margin: 0 0 14px; padding: 10px 12px; border-radius: 10px;
  background: var(--banner-bg); color: var(--banner-ink); font-size: 13px; line-height: 1.45;
}
#banner.show { display: block; }
.now {
  background: var(--panel); border: 1px solid var(--line); border-radius: 18px;
  padding: 22px 20px 16px; margin-bottom: 18px;
}
.now-head { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 8px; }
.now-titles { flex: 1; min-width: 0; }
#cover {
  width: 72px; height: 72px; border-radius: 14px; object-fit: cover; flex: 0 0 auto;
  background: var(--track); display: none;
}
#cover.show { display: block; }
#name { font-size: 24px; font-weight: 650; line-height: 1.25; margin: 0 0 6px; }
#meta { color: var(--dim); font-size: 15px; margin: 0; }
#state {
  font-size: 13px; color: var(--go); border: 1px solid var(--state-line); border-radius: 999px;
  padding: 3px 10px; white-space: nowrap; flex: 0 0 auto; margin-top: 2px;
}
.lyric-stage {
  text-align: center;
  padding: 8px 6px 10px;
  height: 5.8em;
  overflow: hidden;
}
.lyric-focus { height: 100%; }
#lyric {
  font-family: "Songti SC", "STSong", "Source Han Serif SC", "Noto Serif SC", "SimSun", "PMingLiU", serif;
  color: var(--ink);
  font-size: 22px;
  font-weight: 600;
  line-height: 1.5;
  letter-spacing: .03em;
  height: 3em;
  overflow: hidden;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
}
#lyric-extra {
  color: var(--dim);
  font-size: 12px;
  line-height: 1.45;
  opacity: .5;
  height: 1.45em;
  margin: 6px 0 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.lyric-stage.lift .lyric-focus {
  animation: lyric-lift .48s ease;
}
@keyframes lyric-lift {
  from { opacity: .28; transform: translateY(7px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .lyric-stage.lift .lyric-focus { animation: none; }
}
#lyric-panel { margin: 10px 0 0; border-top: 1px solid var(--line); padding-top: 8px; }
#lyric-toggle {
  width: 100%; min-height: 44px; padding: 0 6px; border: 0; border-radius: 8px;
  background: transparent; color: var(--copper); font-size: 15px; text-align: left;
}
#lyric-full {
  display: none;
  position: relative;
  height: 40vh;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 16vh 10px;
  -webkit-overflow-scrolling: touch;
  text-align: center;
}
#lyric-panel.open #lyric-full { display: block; }
#lyric-full button.lrc-line {
  display: block;
  width: 100%;
  min-height: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 10px 8px;
  font-size: 14px;
  line-height: 1.45;
  color: var(--hint);
  opacity: .34;
  text-align: center;
  font-weight: 400;
}
#lyric-full button.lrc-line.near {
  opacity: .62;
  color: var(--dim);
  font-size: 15px;
}
#lyric-full button.lrc-line.cur {
  opacity: 1;
  font-family: "Songti SC", "STSong", "Source Han Serif SC", "Noto Serif SC", "SimSun", "PMingLiU", serif;
  font-size: 21px;
  font-weight: 700;
  line-height: 1.4;
  letter-spacing: .04em;
  padding: 14px 8px;
  color: var(--copper);
  background-image: linear-gradient(90deg, var(--copper) var(--ktv, 12%), rgba(185, 164, 138, .42) var(--ktv, 12%));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
#lyric-full button.lrc-line:active {
  transform: none;
  background: transparent;
}
#lyric-full button.lrc-line.cur:active {
  background-image: linear-gradient(90deg, var(--copper) var(--ktv, 12%), rgba(185, 164, 138, .42) var(--ktv, 12%));
}
@media (prefers-reduced-motion: reduce) {
  #lyric-full button.lrc-line.cur {
    background: none;
    -webkit-text-fill-color: var(--copper);
    color: var(--copper);
  }
}
.time { display: flex; justify-content: space-between; color: var(--dim); font-size: 12px; font-variant-numeric: tabular-nums; }
input[type=range] {
  -webkit-appearance: none; appearance: none; width: 100%; height: 28px; background: transparent; margin: 6px 0;
}
input[type=range]::-webkit-slider-runnable-track { height: 6px; border-radius: 99px; background: var(--track); }
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none; width: 22px; height: 22px; border-radius: 50%;
  background: var(--copper); margin-top: -8px; border: 0;
}
.deck { display: flex; align-items: center; justify-content: center; gap: 18px; margin: 8px 0 12px; }
.loop-btn { width: 100%; min-height: 48px; font-size: 16px; margin: 0 0 4px; }
.loop-btn.on {
  background: var(--copper); color: var(--play-ink); border-color: var(--copper); outline: 0;
}
button {
  font: inherit; color: var(--ink); background: var(--panel); border: 1px solid var(--line);
  border-radius: 16px; min-height: 56px; padding: 0 16px; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
button:active { transform: scale(.97); background: var(--press); }
.skip { width: 72px; font-size: 15px; }
.play {
  width: 92px; height: 92px; border-radius: 50%; background: var(--copper); color: var(--play-ink);
  border: 0; font-size: 22px; font-weight: 700; letter-spacing: .04em;
}
.tools { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tools button { min-height: 52px; font-size: 16px; }
.tools .span2 { grid-column: 1 / -1; }
.vol { margin: 18px 0 14px; }
.vol-head { display: flex; justify-content: space-between; color: var(--dim); font-size: 14px; margin-bottom: 4px; }
.vol-btns { display: flex; gap: 10px; }
.vol-btns button { flex: 1; }
.hint { color: var(--hint); font-size: 12px; line-height: 1.5; text-align: center; margin-top: 18px; }
.on { outline: 2px solid var(--copper); }
</style>
<script>
(function(){
  try {
    var t = localStorage.getItem("lx-remote-theme") || "dark";
    if (t !== "light" && t !== "hi") t = "dark";
    document.documentElement.setAttribute("data-theme", t);
  } catch (e) {}
})();
</script>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand">洛雪遥控 <span class="ver">__PAGE_VER__</span></div>
    <div class="themes" role="radiogroup" aria-label="页面风格">
      <button type="button" data-theme="dark">深色</button>
      <button type="button" data-theme="light">浅色</button>
      <button type="button" data-theme="hi">高对比</button>
    </div>
  </div>
  <div id="banner"></div>
  <section class="now">
    <div class="now-head">
      <img id="cover" alt="">
      <div class="now-titles">
        <h1 id="name">未连接</h1>
        <p id="meta">打开后会读取当前曲目</p>
      </div>
      <div id="state">—</div>
    </div>
    <div class="lyric-stage" id="lyric-stage">
      <div class="lyric-focus">
        <div id="lyric" aria-live="polite"></div>
        <div id="lyric-extra"></div>
      </div>
    </div>
    <input id="seek" type="range" min="0" max="100" value="0" step="1">
    <div class="time"><span id="cur">0:00</span><span id="dur">0:00</span></div>
    <div id="lyric-panel">
      <button type="button" id="lyric-toggle" aria-expanded="false">全文歌词</button>
      <div id="lyric-full">展开后加载</div>
    </div>
  </section>
  <div class="deck">
    <button class="skip" id="prev" type="button">上一曲</button>
    <button class="play" id="toggle" type="button">播放</button>
    <button class="skip" id="next" type="button">下一曲</button>
  </div>
  <button class="loop-btn" id="loop" type="button" aria-pressed="false">单曲循环</button>
  <div class="vol">
    <div class="vol-head"><span>音量</span><span id="voln">—</span></div>
    <input id="vol" type="range" min="0" max="100" value="0" step="1">
    <div class="vol-btns">
      <button id="vdown" type="button">音量 −</button>
      <button id="vup" type="button">音量 +</button>
    </div>
  </div>
  <div class="tools">
    <button id="mute" type="button">静音</button>
    <button id="vmax" type="button">音量最大</button>
    <button id="collect" class="span2" type="button" title="把正在播放的歌加入洛雪桌面端的收藏">收藏当前曲</button>
  </div>
  <p class="hint">手机只访问这个页面。播放、切歌、音量走洛雪开放 API，由电脑上的 启动.bat 代理。</p>
</div>
<script>
var dragSeek = false, dragVol = false, last = null;
var songKey = "", lrcLines = [], lrcCur = -1, lrcLoading = "", lrcPlain = "";
var lrcHold = false, lrcHoldTimer = 0, lrcProgScroll = false, lrcWantTop = -1;
var stampAt = Date.now();
var THEMES = {dark:"#1a1410", light:"#f3eee6", hi:"#000000"};
function applyTheme(name) {
  if (!THEMES[name]) name = "dark";
  document.documentElement.setAttribute("data-theme", name);
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = THEMES[name];
  try { localStorage.setItem("lx-remote-theme", name); } catch (e) {}
  var btns = document.querySelectorAll(".themes [data-theme]");
  for (var i = 0; i < btns.length; i++) {
    btns[i].classList.toggle("picked", btns[i].getAttribute("data-theme") === name);
  }
}
applyTheme((function(){
  try { return localStorage.getItem("lx-remote-theme") || "dark"; } catch (e) { return "dark"; }
})());
document.querySelector(".themes").addEventListener("click", function (ev) {
  var btn = ev.target.closest("[data-theme]");
  if (btn) applyTheme(btn.getAttribute("data-theme"));
});
function $(id) { return document.getElementById(id); }
function fmt(sec) {
  sec = Math.max(0, Math.floor(Number(sec) || 0));
  return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
}
function label(st) {
  return ({playing:"播放中", paused:"已暂停", stoped:"已停止", error:"出错"}[st] || st || "—");
}
function banner(msg) {
  var el = $("banner");
  if (!msg) { el.className = ""; el.textContent = ""; return; }
  el.className = "show";
  el.textContent = msg;
}
function paint(s) {
  last = s || {};
  $("name").textContent = last.name || "没有在播的歌";
  var meta = [last.singer, last.albumName].filter(Boolean).join("  ·  ") || " ";
  if (last.playbackRate && Number(last.playbackRate) !== 1) meta += "  ×" + last.playbackRate;
  $("meta").textContent = meta;
  stampAt = Date.now();
  $("state").textContent = label(last.status);
  $("toggle").textContent = last.status === "playing" ? "暂停" : "播放";
  var cover = $("cover");
  if (last.picUrl && /^https?:\/\//i.test(last.picUrl)) {
    if (cover.getAttribute("data-src") !== last.picUrl) {
      cover.setAttribute("data-src", last.picUrl);
      cover.src = last.picUrl;
    }
    cover.className = "show";
  } else {
    cover.removeAttribute("src");
    cover.removeAttribute("data-src");
    cover.className = "";
  }
  if (!dragSeek) {
    $("seek").max = Math.max(1, Math.floor(Number(last.duration) || 0));
    $("seek").value = Math.floor(Number(last.progress) || 0);
  }
  $("cur").textContent = fmt(last.progress);
  $("dur").textContent = fmt(last.duration);
  if (!dragVol) $("vol").value = Math.round(Number(last.volume) || 0);
  $("voln").textContent = last.mute ? "静音" : String(Math.round(Number(last.volume) || 0));
  $("mute").textContent = last.mute ? "取消静音" : "静音";
  $("mute").className = last.mute ? "on" : "";
  $("collect").textContent = last.collect ? "已收藏当前曲" : "收藏当前曲";
  $("collect").className = last.collect ? "span2 on" : "span2";
  var key = (last.name || "") + "|" + (last.singer || "");
  if (key !== songKey) {
    lrcLines = [];
    lrcCur = -1;
    lrcPlain = "";
    paintStage(-1);
    if (lrcLoading !== key) {
      lrcLoading = key;
      loadLyric(last);
    }
  } else {
    paintLrc(liveProgress());
  }
}
function liveProgress() {
  var p = Number(last && last.progress) || 0;
  if (last && last.status === "playing" && !dragSeek) {
    p += (Date.now() - stampAt) / 1000 * (Number(last.playbackRate) || 1);
  }
  return p;
}
function extraOf(line) {
  var extra = (last && last.lyricLineAllText) || "";
  if (extra && extra !== line) {
    return extra.split("\n").filter(function (p) { return p && p !== line; }).join("\n");
  }
  return "";
}
function paintStage(idx) {
  var cur = "";
  if (lrcLines.length && idx >= 0) {
    cur = lrcLines[idx].text;
  } else {
    cur = (last && last.lyricLineText) || "暂无歌词";
  }
  var extra = extraOf(cur);
  var changed = cur !== $("lyric").textContent;
  $("lyric").textContent = cur || "暂无歌词";
  $("lyric-extra").textContent = extra;
  if (changed) {
    var stage = $("lyric-stage");
    stage.classList.remove("lift");
    void stage.offsetWidth;
    stage.classList.add("lift");
  }
}
function parseLrc(text) {
  var lines = [];
  var skip = /^\[(ar|ti|al|by|offset|kuwo|ver|total):/i;
  String(text || "").replace(/\r/g, "").split("\n").forEach(function (raw) {
    raw = raw.trim();
    if (!raw || skip.test(raw)) return;
    var stamps = [];
    var rest = raw.replace(/\[(\d{1,2}):(\d{1,2}(?:\.\d+)?)\]/g, function (_, m, s) {
      stamps.push(parseInt(m, 10) * 60 + parseFloat(s));
      return "";
    }).replace(/<[^>]+>/g, "").trim();
    if (!stamps.length || !rest) return;
    stamps.forEach(function (t) { lines.push({ t: t, text: rest }); });
  });
  lines.sort(function (a, b) { return a.t - b.t; });
  return lines;
}
function renderLrcList() {
  var box = $("lyric-full");
  box.innerHTML = "";
  if (!lrcLines.length) {
    box.textContent = "这首没有逐句歌词";
    return;
  }
  lrcLines.forEach(function (line, i) {
    var p = document.createElement("button");
    p.type = "button";
    p.className = "lrc-line";
    p.textContent = line.text;
    p.onclick = function () { act("/api/seek?offset=" + line.t); };
    box.appendChild(p);
  });
}
function lyricPanelOpen() {
  return $("lyric-panel").classList.contains("open");
}
function holdLrcFollow() {
  if (lrcProgScroll) return;
  lrcHold = true;
  if (lrcHoldTimer) clearTimeout(lrcHoldTimer);
  lrcHoldTimer = setTimeout(function () {
    lrcHold = false;
    followLrcLine(lrcCur);
  }, 2000);
}
function lineScrollTarget(box, el) {
  var top = el.offsetTop - box.clientHeight / 2 + el.offsetHeight / 2;
  if (el.offsetParent !== box) {
    var br = box.getBoundingClientRect();
    var er = el.getBoundingClientRect();
    top = box.scrollTop + (er.top + er.height / 2) - (br.top + box.clientHeight / 2);
  }
  if (top < 0) top = 0;
  var max = Math.max(0, box.scrollHeight - box.clientHeight);
  if (top > max) top = max;
  return top;
}
function followLrcLine(idx) {
  var box = $("lyric-full");
  if (!box || !lyricPanelOpen() || lrcHold || idx == null || idx < 0) return;
  var el = box.children[idx];
  if (!el || !el.classList || !el.classList.contains("lrc-line")) return;
  if (!box.clientHeight) {
    setTimeout(function () { followLrcLine(idx); }, 50);
    return;
  }
  var top = lineScrollTarget(box, el);
  if (Math.abs(box.scrollTop - top) < 2) return;
  lrcProgScroll = true;
  lrcWantTop = top;
  box.scrollTop = top;
  setTimeout(function () { lrcProgScroll = false; }, 120);
}
function followLrcSoon(idx) {
  requestAnimationFrame(function () {
    followLrcLine(idx);
    setTimeout(function () { followLrcLine(idx); }, 60);
  });
}
function ktvRatio(progress, idx) {
  if (idx < 0 || !lrcLines.length) return 0;
  var t0 = lrcLines[idx].t;
  var t1 = idx + 1 < lrcLines.length ? lrcLines[idx + 1].t : t0 + 5;
  if (t1 <= t0) return 1;
  var r = (progress - t0) / (t1 - t0);
  if (r < 0) return 0;
  if (r > 1) return 1;
  return r;
}
function markLrcClasses(idx) {
  var nodes = $("lyric-full").children;
  var i, node;
  for (i = 0; i < nodes.length; i++) {
    node = nodes[i];
    if (!node.classList || !node.classList.contains("lrc-line")) continue;
    if (i === idx) node.className = "lrc-line cur";
    else if (idx >= 0 && (i === idx - 1 || i === idx + 1)) node.className = "lrc-line near";
    else node.className = "lrc-line";
    if (i !== idx) node.style.removeProperty("--ktv");
  }
}
function paintKtvWipe(idx, progress) {
  if (!lyricPanelOpen() || idx < 0) return;
  var node = $("lyric-full").children[idx];
  if (node && node.style) node.style.setProperty("--ktv", (ktvRatio(progress, idx) * 100).toFixed(1) + "%");
}
function paintLrc(progress) {
  var idx = -1;
  if (lrcLines.length) {
    progress = Number(progress) || 0;
    for (var i = 0; i < lrcLines.length; i++) {
      if (lrcLines[i].t <= progress + 0.05) idx = i;
    }
  }
  paintStage(idx);
  if (!lrcLines.length) return;
  if (idx !== lrcCur) {
    lrcCur = idx;
    markLrcClasses(idx);
    followLrcSoon(idx);
  }
  paintKtvWipe(idx, progress);
}
function fillLyricPanel() {
  if (!lyricPanelOpen()) return;
  if (lrcLines.length) {
    lrcHold = false;
    renderLrcList();
    lrcCur = -1;
    paintLrc(liveProgress());
    followLrcSoon(lrcCur);
    return;
  }
  $("lyric-full").textContent = lrcPlain || "这首没有逐句歌词";
}
async function loadLyric(s) {
  var key = ((s && s.name) || "") + "|" + ((s && s.singer) || "");
  if (lyricPanelOpen()) $("lyric-full").textContent = "加载中…";
  try {
    var data = await apiRaw("/api/lyric");
    var nowKey = ((last && last.name) || "") + "|" + ((last && last.singer) || "");
    if (key !== nowKey) return;
    lrcLines = parseLrc(data.lyric || "");
    lrcPlain = (data.lyric || "").replace(/^\[[^\]]+\]\s*/gm, "").trim();
    songKey = key;
    lrcLoading = "";
    lrcCur = -1;
    fillLyricPanel();
    paintLrc(liveProgress());
  } catch (e) {
    if (lrcLoading === key) lrcLoading = "";
    if (lyricPanelOpen()) $("lyric-full").textContent = e.message || "歌词读取失败";
    paintStage(-1);
  }
}
async function apiRaw(path) {
  var r = await fetch(path, { cache: "no-store" });
  var data = await r.json();
  if (!data.ok) throw new Error(data.error || "请求失败");
  return data;
}
function applyLoop(on) {
  on = !!on;
  var btn = $("loop");
  if (!btn) return;
  btn.className = on ? "loop-btn on" : "loop-btn";
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.textContent = on ? "单曲循环 · 开" : "单曲循环";
  try { localStorage.setItem("lx-remote-loop", on ? "1" : "0"); } catch (e) {}
}
applyLoop((function(){
  try { return localStorage.getItem("lx-remote-loop") === "1"; } catch (e) { return false; }
})());
async function api(path) {
  var data = await apiRaw(path);
  if (typeof data.loopOne === "boolean") applyLoop(data.loopOne);
  return data.status;
}
async function act(path) {
  try {
    paint(await api(path));
    banner("");
  } catch (e) { banner(e.message || String(e)); }
}
async function refresh() {
  try {
    var s = await api("/api/status");
    if (!dragSeek && !dragVol) paint(s);
    banner("");
  } catch (e) { banner("连不上洛雪：" + (e.message || e)); }
}
$("prev").onclick = function () { act("/api/prev"); };
$("next").onclick = function () { act("/api/next"); };
$("toggle").onclick = function () { act("/api/toggle"); };
$("loop").onclick = function () {
  var on = $("loop").getAttribute("aria-pressed") === "true";
  act("/api/loop?on=" + (on ? "false" : "true"));
};
$("mute").onclick = function () {
  act("/api/mute?mute=" + (last && last.mute ? "false" : "true"));
};
$("vmax").onclick = function () { act("/api/volume?volume=100"); };
$("collect").onclick = function () {
  act(last && last.collect ? "/api/uncollect" : "/api/collect");
};
$("vdown").onclick = function () { act("/api/volume?volume=" + encodeURIComponent("-10")); };
$("vup").onclick = function () { act("/api/volume?volume=" + encodeURIComponent("+10")); };
$("seek").addEventListener("pointerdown", function () { dragSeek = true; });
$("vol").addEventListener("pointerdown", function () { dragVol = true; });
$("seek").addEventListener("change", function () {
  dragSeek = false;
  act("/api/seek?offset=" + encodeURIComponent($("seek").value));
});
$("vol").addEventListener("change", function () {
  dragVol = false;
  act("/api/volume?volume=" + encodeURIComponent($("vol").value));
});
(function bindLrcPanelScroll() {
  var box = $("lyric-full");
  if (!box) return;
  var startY = 0;
  box.addEventListener("touchstart", function (e) {
    startY = e.touches && e.touches[0] ? e.touches[0].clientY : 0;
  }, false);
  box.addEventListener("touchmove", function (e) {
    var y = e.touches && e.touches[0] ? e.touches[0].clientY : startY;
    if (Math.abs(y - startY) > 8) holdLrcFollow();
  }, false);
  box.addEventListener("wheel", holdLrcFollow, false);
  box.addEventListener("scroll", function () {
    if (lrcProgScroll) return;
    if (lrcWantTop >= 0 && Math.abs(box.scrollTop - lrcWantTop) < 8) return;
    holdLrcFollow();
  }, false);
})();
$("lyric-toggle").onclick = function () {
  var open = !lyricPanelOpen();
  $("lyric-panel").classList.toggle("open", open);
  $("lyric-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  $("lyric-toggle").textContent = open ? "收起全文" : "全文歌词";
  if (!open) return;
  if (!last) {
    $("lyric-full").textContent = "还没有曲目";
    return;
  }
  var key = (last.name || "") + "|" + (last.singer || "");
  if (lrcLines.length) fillLyricPanel();
  else if (lrcLoading === key) $("lyric-full").textContent = "加载中…";
  else loadLyric(last);
};
$("cover").onerror = function () { this.className = ""; };
setInterval(refresh, 2000);
setInterval(function () {
  if (last && lrcLines.length && !dragSeek) paintLrc(liveProgress());
}, 400);
(function ktvLoop() {
  if (lyricPanelOpen() && last && lrcLines.length && !dragSeek) {
    paintKtvWipe(lrcCur, liveProgress());
  }
  requestAnimationFrame(ktvLoop);
})();
refresh();
</script>
</body>
</html>
"""


SIMPLE_API = {
    "/api/play": "/play",
    "/api/pause": "/pause",
    "/api/next": "/skip-next",
    "/api/skip-next": "/skip-next",
    "/api/prev": "/skip-prev",
    "/api/skip-prev": "/skip-prev",
    "/api/collect": "/collect",
    "/api/uncollect": "/uncollect",
}


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _usable_lan_ip(ip):
    if not ip or "." not in ip:
        return False
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    return True


def lan_ips():
    """本机局域网 IPv4，不依赖 ipconfig / ifconfig。"""
    found = []

    def add(ip):
        if _usable_lan_ip(ip) and ip not in found:
            found.append(ip)

    # UDP connect 不真正发包，只用来选出口网卡；目标地址任意可达路由即可
    for probe in ("1.1.1.1", "8.8.8.8", "192.168.31.1"):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.4)
            sock.connect((probe, 80))
            add(sock.getsockname()[0])
        except Exception:
            pass
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
        if found:
            break
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(item[4][0])
    except Exception:
        pass
    return found


def _say_launch(msg):
    print(msg)
    sys.stdout.flush()


def _base_host_port(base_url):
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or ""
    port = parsed.port if parsed.port is not None else DEFAULT_PORT
    scheme = parsed.scheme or "http"
    return host, int(port), scheme


def is_local_api_host(host):
    host = (host or "").strip().lower()
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return True
    return host in lan_ips()


def api_is_up(base_url, token, timeout=1.2):
    try:
        get_status(base_url, token, timeout)
        return True
    except Exception:
        return False


def _win_run(cmd):
    kwargs = {"stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = _WIN_CREATE_NO_WINDOW
    return subprocess.check_output(cmd, **kwargs)


def _pgrep_exact(name):
    try:
        subprocess.check_call(
            ["pgrep", "-x", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def lx_desktop_running():
    if sys.platform == "win32":
        try:
            raw = _win_run(["tasklist", "/FI", "IMAGENAME eq lx-music-desktop.exe", "/NH"])
            text = raw.decode("mbcs", "replace").lower()
            return "lx-music-desktop.exe" in text
        except Exception:
            return False
    # Linux comm 最长 15 字符，lx-music-desktop 会被截成 lx-music-deskto
    for name in ("lx-music-desktop", "lx-music-deskto"):
        if _pgrep_exact(name):
            return True
    try:
        raw = subprocess.check_output(
            ["ps", "-ax", "-o", "args="],
            stderr=subprocess.DEVNULL,
        )
        text = raw.decode("utf-8", "replace")
    except Exception:
        return False
    for line in text.splitlines():
        low = line.lower()
        if "lx-music-desktop" not in low:
            continue
        if "lx_control" in low:
            continue
        return True
    return False


def _looks_like_lx_exe(path):
    if not path:
        return False
    name = os.path.basename(path.rstrip("\\/"))
    lower = name.lower()
    if lower.endswith(".app"):
        return os.path.isdir(path) and ("lx-music" in lower or "洛雪" in name)
    if not os.path.isfile(path):
        return False
    if lower in ("lx-music-desktop.exe", "lx-music-desktop"):
        return True
    if lower.endswith(".appimage") and "lx-music" in lower:
        return True
    return False


def _lx_exe_names():
    if sys.platform == "win32":
        return ("lx-music-desktop.exe",)
    if sys.platform == "darwin":
        return ("lx-music-desktop.app", "LX Music.app")
    return ("lx-music-desktop",)


def _lx_exes_in_dir(folder):
    """当前目录下一层：精确名、AppImage、.app，以及 /opt/lx-music-desktop/ 里的二进制。"""
    found = []
    folder = os.path.abspath(folder or "")
    if not folder or not os.path.isdir(folder):
        return found
    for name in _lx_exe_names():
        path = os.path.join(folder, name)
        if _looks_like_lx_exe(path) and path not in found:
            found.append(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return found
    for name in names:
        path = os.path.join(folder, name)
        if _looks_like_lx_exe(path) and path not in found:
            found.append(path)
            continue
        if not os.path.isdir(path):
            continue
        lower = name.lower()
        if "lx-music" not in lower and "洛雪" not in name:
            continue
        nested = os.path.join(path, "lx-music-desktop")
        if _looks_like_lx_exe(nested) and nested not in found:
            found.append(nested)
        nested_app = os.path.join(path, "lx-music-desktop.app")
        if _looks_like_lx_exe(nested_app) and nested_app not in found:
            found.append(nested_app)
    return found


def _lx_exes_from_parents(start, limit=8):
    """从脚本所在目录向上找桌面端，兼容放在安装目录子文件夹（如 ...\\lx-music-desktop\\lxpy）。"""
    found = []
    folder = os.path.abspath(start or "")
    if not folder:
        return found
    if os.path.isfile(folder):
        folder = os.path.dirname(folder)
    seen = set()
    steps = max(1, int(limit))
    for _ in range(steps):
        if not folder or folder in seen:
            break
        seen.add(folder)
        for path in _lx_exes_in_dir(folder):
            if path not in found:
                found.append(path)
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return found


def _strip_icon_index(path):
    text = (path or "").strip().strip('"')
    if text.lower().endswith(",0") and not os.path.exists(text):
        text = text[:-2]
    return text.strip('"')


def _win_registry_exes():
    found = []
    try:
        import winreg
    except ImportError:
        return found
    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, sub in roots:
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    child = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    item = winreg.OpenKey(key, child)
                except OSError:
                    continue
                try:
                    name = str(winreg.QueryValueEx(item, "DisplayName")[0])
                except OSError:
                    name = ""
                blob = name.lower()
                if "lx-music" not in blob and "洛雪" not in name:
                    winreg.CloseKey(item)
                    continue
                for field in ("DisplayIcon", "InstallLocation", "DisplayName"):
                    try:
                        raw = str(winreg.QueryValueEx(item, field)[0])
                    except OSError:
                        continue
                    raw = _strip_icon_index(raw)
                    if field == "InstallLocation":
                        raw = os.path.join(raw, "lx-music-desktop.exe")
                    if _looks_like_lx_exe(raw) and raw not in found:
                        found.append(raw)
                winreg.CloseKey(item)
        finally:
            winreg.CloseKey(key)
    return found


def _candidate_lx_exes(explicit=None):
    ordered = []

    def add(path):
        path = os.path.expandvars(os.path.expanduser(path or ""))
        if _looks_like_lx_exe(path) and path not in ordered:
            ordered.append(path)

    add(explicit)
    add(env_or("LX_APP", ""))
    add(env_or("LX_EXE", ""))
    add(load_state().get("lxExe") or "")
    for item in _lx_exes_from_parents(_script_dir()):
        add(item)
    cwd = os.getcwd()
    if os.path.abspath(cwd) != os.path.abspath(_script_dir()):
        for item in _lx_exes_from_parents(cwd):
            add(item)

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or ""
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
        for root in (
            os.path.join(local, "lx-music-desktop", "lx-music-desktop.exe"),
            os.path.join(local, "Programs", "lx-music-desktop", "lx-music-desktop.exe"),
            os.path.join(pf, "lx-music-desktop", "lx-music-desktop.exe"),
            os.path.join(pf86, "lx-music-desktop", "lx-music-desktop.exe"),
        ):
            add(root)
        for letter in "CDEFG":
            add(r"{0}:\Program Files\lx-music-desktop\lx-music-desktop.exe".format(letter))
            add(r"{0}:\Program Files (x86)\lx-music-desktop\lx-music-desktop.exe".format(letter))
        for item in _win_registry_exes():
            add(item)
    elif sys.platform == "darwin":
        for folder in ("/Applications", os.path.expanduser("~/Applications")):
            for item in _lx_exes_in_dir(folder):
                add(item)
        add("/Applications/lx-music-desktop.app")
        add("/Applications/LX Music.app")
        add(os.path.expanduser("~/Applications/lx-music-desktop.app"))
        add(os.path.expanduser("~/Applications/LX Music.app"))
    else:
        which = None
        try:
            import shutil
            which = shutil.which("lx-music-desktop")
        except Exception:
            which = None
        add(which)
        home = os.path.expanduser("~")
        for path in (
            "/usr/bin/lx-music-desktop",
            "/usr/local/bin/lx-music-desktop",
            os.path.join(home, ".local", "bin", "lx-music-desktop"),
            "/opt/lx-music-desktop/lx-music-desktop",
            "/snap/bin/lx-music-desktop",
            os.path.join(home, ".local", "share", "flatpak", "exports", "bin", "lx-music-desktop"),
            "/var/lib/flatpak/exports/bin/lx-music-desktop",
        ):
            add(path)
        for folder in (
            "/opt",
            os.path.join(home, "Applications"),
            os.path.join(home, ".local", "bin"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Downloads"),
        ):
            for item in _lx_exes_in_dir(folder):
                add(item)

    return ordered


def find_lx_exe(explicit=None):
    found = _candidate_lx_exes(explicit)
    return found[0] if found else ""


def _lx_config_v2_path(exe=None):
    """洛雪设置文件：LxDatas/config_v2.json（便携版优先，其次各平台默认目录）。"""
    candidates = []

    def add(path):
        path = os.path.expandvars(os.path.expanduser(path or ""))
        if path and path not in candidates:
            candidates.append(path)

    exe = os.path.abspath(exe) if exe else ""
    if exe:
        folder = os.path.dirname(exe)
        if exe.rstrip("\\/").lower().endswith(".app"):
            folder = os.path.dirname(exe)
        portable = os.path.join(folder, "portable")
        portable_cfg = os.path.join(portable, "userData", "LxDatas", "config_v2.json")
        if os.path.isdir(portable):
            return portable_cfg
        add(portable_cfg)

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or ""
        if appdata:
            add(os.path.join(appdata, "lx-music-desktop", "LxDatas", "config_v2.json"))
    elif sys.platform == "darwin":
        add("~/Library/Application Support/lx-music-desktop/LxDatas/config_v2.json")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        add(os.path.join(xdg, "lx-music-desktop", "LxDatas", "config_v2.json"))
        add("~/.var/app/cn.toside.lx-music-desktop/config/lx-music-desktop/LxDatas/config_v2.json")
        add(
            "~/.var/app/io.github.lyswhut.lx-music-desktop/config/lx-music-desktop/LxDatas/config_v2.json"
        )

    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0] if candidates else ""


def _write_json_atomic(path, data):
    folder = os.path.dirname(path)
    tmp = os.path.join(folder, "config_v2.{}.temp".format(int(time.time() * 1000) % 1000000000))
    text = json.dumps(data, ensure_ascii=False, indent="\t")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _merge_lx_config_v2(exe=None, port=None, enable_open_api=False, disable_auto_update=False):
    """仅合并指定项，不改 bindLan / showChangeLog 等其它项。

    配置文件缺失或损坏时不整文件重写。
    返回 already / enabled / missing / failed。
    """
    if not enable_open_api and not disable_auto_update:
        return "already"
    path = _lx_config_v2_path(exe)
    if not path or not os.path.isfile(path):
        return "missing"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return "failed"
    if not isinstance(data, dict):
        return "failed"
    setting = data.get("setting")
    if not isinstance(setting, dict):
        return "failed"

    changed = False
    if enable_open_api:
        want_port = str(DEFAULT_PORT if port is None else port)
        if setting.get("openAPI.enable") is not True:
            setting["openAPI.enable"] = True
            changed = True
        current_port = setting.get("openAPI.port")
        if current_port is None or current_port == "":
            setting["openAPI.port"] = want_port
            changed = True
    # 官方键 common.tryAutoUpdate =「发现新版本时尝试自动下载更新」
    if disable_auto_update and setting.get("common.tryAutoUpdate") is not False:
        setting["common.tryAutoUpdate"] = False
        changed = True
    if not changed:
        return "already"
    data["setting"] = setting
    try:
        _write_json_atomic(path, data)
    except Exception:
        return "failed"
    return "enabled"


def ensure_open_api_setting(exe=None, port=None):
    """合并 openAPI.enable（及缺省端口），并关闭自动下载更新。

    开放 API 宜在洛雪未运行时写入，否则进程内设置会盖回文件。
    返回 already / enabled / missing / failed。
    """
    return _merge_lx_config_v2(
        exe, port, enable_open_api=True, disable_auto_update=True
    )


def _cmd_exists(name):
    try:
        import shutil
        return bool(shutil.which(name))
    except Exception:
        return False


def _linux_desktop_installed(desktop_id):
    for folder in (
        "/usr/share/applications",
        "/usr/local/share/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/snapd/desktop/applications",
    ):
        if os.path.isfile(os.path.join(folder, desktop_id + ".desktop")):
            return True
    return False


def _flatpak_app_installed(app_id):
    if not _cmd_exists("flatpak"):
        return False
    try:
        subprocess.check_call(
            ["flatpak", "info", app_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _launch_lx_by_platform_name():
    """找不到可执行文件时：macOS 按应用名 open -a；Linux 仅在已安装时 gtk-launch / flatpak / snap。"""
    if sys.platform == "darwin":
        for name in ("lx-music-desktop", "LX Music"):
            try:
                ret = subprocess.call(
                    ["open", "-a", name],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if ret == 0:
                    return True
            except Exception:
                continue
        return False
    if sys.platform == "win32":
        return False
    if _linux_desktop_installed("lx-music-desktop") and _cmd_exists("gtk-launch"):
        try:
            subprocess.Popen(
                ["gtk-launch", "lx-music-desktop"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass
    for app_id in (
        "cn.toside.lx-music-desktop",
        "io.github.lyswhut.lx-music-desktop",
    ):
        if _flatpak_app_installed(app_id):
            try:
                subprocess.Popen(
                    ["flatpak", "run", app_id],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                continue
    if _cmd_exists("snap") and os.path.exists("/snap/bin/lx-music-desktop"):
        try:
            subprocess.Popen(
                ["snap", "run", "lx-music-desktop"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass
    return False


def _ensure_executable(path):
    if sys.platform == "win32" or not path:
        return
    try:
        if os.path.isfile(path) and not os.access(path, os.X_OK):
            mode = os.stat(path).st_mode
            os.chmod(path, mode | 0o111)
    except OSError:
        pass


def launch_lx_exe(exe):
    if sys.platform == "darwin" and exe.rstrip("/").endswith(".app"):
        subprocess.Popen(
            ["open", "-a", exe],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    if sys.platform != "win32":
        _ensure_executable(exe)
    kwargs = {
        "cwd": os.path.dirname(exe) or None,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _WIN_DETACHED | _WIN_NEW_GROUP
    subprocess.Popen([exe], **kwargs)


def ensure_local_lx(base_url, token, timeout, explicit_exe=None, wait_s=None, launch=True):
    """网页遥控：本机 API 不通时尝试启动洛雪桌面端。返回可能改过的 base_url。"""
    host, port, scheme = _base_host_port(base_url)
    exe = find_lx_exe(explicit_exe)
    if is_local_api_host(host):
        upd_cfg = _merge_lx_config_v2(
            exe or explicit_exe, port, enable_open_api=False, disable_auto_update=True
        )
        if upd_cfg == "enabled":
            _say_launch(
                "已关闭洛雪「发现新版本时尝试自动下载更新」。"
                "桌面端若已在运行，可能需重启一次后才会按新设置检查更新。"
            )
        elif upd_cfg == "failed":
            _say_launch("未能写入洛雪自动更新设置（配置缺失或损坏时不会整文件覆盖）。")

    if api_is_up(base_url, token, min(timeout, 1.5)):
        return base_url
    loop_url = "{}://127.0.0.1:{}".format(scheme, port)
    if host not in ("127.0.0.1", "localhost") and api_is_up(loop_url, token, 1.2):
        _say_launch("本机 127.0.0.1:{} 已可连，改走回环（不必勾选局域网访问）。".format(port))
        return loop_url

    local = is_local_api_host(host)
    if not local:
        _say_launch(
            "洛雪 API 连不上 {}，目标不是本机，不会自动启动桌面端。".format(base_url)
        )
        return base_url

    if not launch:
        return base_url

    wait_s = DEFAULT_LAUNCH_WAIT if wait_s is None else float(wait_s)
    already = lx_desktop_running()
    if already:
        _say_launch(
            "洛雪进程已在运行，但开放 API 连不上。请在洛雪里：设置 → 开放 API → 勾选「启用开放 API 服务」（端口 {}）。"
            "已在运行时改配置不会立刻生效，需重启洛雪或手动勾选。".format(port)
        )
    else:
        if not exe:
            exe = find_lx_exe(explicit_exe)
        api_cfg = ensure_open_api_setting(exe, port)
        if api_cfg == "enabled":
            _say_launch("已在洛雪配置中启用开放 API（端口沿用已有值，缺省 {}）。".format(port))
        elif api_cfg == "already":
            _say_launch("洛雪配置里已启用开放 API。")
        elif api_cfg == "missing":
            _say_launch(
                "未找到洛雪配置文件，无法自动勾选开放 API。启动后若仍连不上，请手动：设置 → 开放 API → 启用。"
            )
        else:
            _say_launch("未能自动写入开放 API 配置，请稍后在洛雪里手动勾选启用。")
        launched = False
        if exe:
            _say_launch("未连上洛雪，正在启动：{}".format(exe))
            try:
                launch_lx_exe(exe)
                launched = True
                save_state({"lxExe": exe})
            except Exception as exc:
                _say_launch("启动洛雪失败：{}".format(exc))
                return base_url
        elif _launch_lx_by_platform_name():
            launched = True
            if sys.platform == "darwin":
                _say_launch("未连上洛雪，已用 open -a 按应用名启动桌面端。")
            else:
                _say_launch("未连上洛雪，已按系统已安装的桌面项/flatpak/snap 启动。")
        if not launched:
            if sys.platform == "darwin":
                hint = "lx-music-desktop.app（常见于 /Applications）"
            elif sys.platform == "win32":
                hint = "lx-music-desktop.exe"
            else:
                hint = "lx-music-desktop 或 lx-music-desktop*.AppImage"
            _say_launch(
                "未找到洛雪桌面端（{}）。请先安装洛雪音乐，"
                "或设置环境变量 LX_APP / 启动参数 --lx-exe，"
                "或在 lx_remote_state.json 写入 \"lxExe\"。".format(hint)
            )
            return base_url

    _say_launch("等待开放 API（最多 {:.0f} 秒）…".format(wait_s))
    deadline = time.time() + wait_s
    urls = [base_url]
    if loop_url not in urls:
        urls.append(loop_url)
    while time.time() < deadline:
        for url in urls:
            if api_is_up(url, token, 1.0):
                if url != base_url:
                    _say_launch("已连上 {}（原地址 {} 不通）。".format(url, base_url))
                else:
                    _say_launch("已连上 {}".format(url))
                return url
        time.sleep(0.6)

    _say_launch(
        "等待超时：洛雪窗口可能已打开，但 {}:{} 仍无开放 API。请确认已启用开放 API，端口为 {}。".format(
            host or "127.0.0.1", port, port
        )
    )
    return base_url


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class WebHandler(BaseHTTPRequestHandler):
    server_version = "LXRemote/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, "application/json; charset=utf-8", json_bytes(payload))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            html = INDEX_HTML.replace("__PAGE_VER__", PAGE_VER)
            self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path.startswith("/api/"):
            self._api(path, urllib.parse.parse_qs(parsed.query))
            return
        self._send(404, "text/plain; charset=utf-8", "Not Found".encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._json(404, {"ok": False, "error": "Not Found"})

    def _api(self, path, qs):
        base = self.server.lx_base
        token = self.server.lx_token
        timeout = self.server.lx_timeout
        try:
            if path == "/api/lyric":
                code, _, text = call(base, "/lyric", token=token, timeout=timeout)
                if code != 200:
                    raise RuntimeError("读取歌词失败 HTTP {}：{}".format(code, (text or "")[:200]))
                self._json(200, {"ok": True, "lyric": text})
                return
            if path == "/api/lyric-all":
                code, _, text = call(base, "/lyric-all", token=token, timeout=timeout)
                if code != 200:
                    raise RuntimeError("读取全部歌词失败 HTTP {}：{}".format(code, (text or "")[:200]))
                data = parse_status_body(text)
                self._json(200, {"ok": True, "lyricAll": data or {}})
                return
            if path == "/api/loop":
                raw = ((qs.get("on") or qs.get("loop") or [None])[0] or "").lower()
                if raw in ("true", "1", "on", "yes"):
                    set_loop_one(self.server, True)
                elif raw in ("false", "0", "off", "no"):
                    set_loop_one(self.server, False)
                status = get_status(base, token, timeout)
                self._json(200, {
                    "ok": True,
                    "status": status,
                    "loopOne": bool(getattr(self.server, "lx_loop_one", False)),
                })
                return
            status = self._dispatch(path, qs, base, token, timeout)
        except Exception as exc:
            self._json(502, {"ok": False, "error": str(exc)})
            return
        self._json(200, {
            "ok": True,
            "status": status,
            "loopOne": bool(getattr(self.server, "lx_loop_one", False)),
        })

    def _dispatch(self, path, qs, base, token, timeout):
        if path == "/api/status":
            return get_status(base, token, timeout)
        if path == "/api/toggle":
            data = get_status(base, token, timeout)
            target = "/pause" if data.get("status") == "playing" else "/play"
            _, status = do_control(base, target, token, timeout)
            return status or get_status(base, token, timeout)
        if path == "/api/volume":
            raw = (qs.get("volume") or [None])[0]
            if raw is None or raw == "":
                return get_status(base, token, timeout)
            current = get_status(base, token, timeout)
            value = parse_volume_arg(raw, current.get("volume"))
            if current.get("mute") is True:
                do_control(base, "/mute", token, timeout, after_status=False, query={"mute": "false"})
            _, status = do_control(base, "/volume", token, timeout, query={"volume": str(value)})
            return status or get_status(base, token, timeout)
        if path == "/api/mute":
            raw = ((qs.get("mute") or [None])[0] or "").lower()
            if raw in ("true", "false"):
                flag = raw
            else:
                flag = "false" if get_status(base, token, timeout).get("mute") else "true"
            _, status = do_control(base, "/mute", token, timeout, query={"mute": flag})
            return status or get_status(base, token, timeout)
        if path == "/api/seek":
            raw = (qs.get("offset") or [None])[0]
            if raw is None or raw == "":
                raise RuntimeError("缺少 offset")
            offset = parse_seek_arg(raw)
            _, status = do_control(
                base, "/seek", token, timeout, query={"offset": "{:.3f}".format(offset)}
            )
            return status or get_status(base, token, timeout)
        if path in SIMPLE_API:
            if path in ("/api/next", "/api/skip-next", "/api/prev", "/api/skip-prev"):
                mark_user_skip(self.server)
            _, status = do_control(base, SIMPLE_API[path], token, timeout)
            return status or get_status(base, token, timeout)
        raise RuntimeError("未知接口：{}".format(path))


def _enable_win_console():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint(0)
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _load_segno():
    try:
        import segno
        return segno
    except ImportError:
        pass
    pip_cmd = [sys.executable, "-m", "pip", "install", "segno==1.6.6"]
    try:
        print("正在安装 segno（生成微信可扫的二维码）…")
        sys.stdout.flush()
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = _WIN_CREATE_NO_WINDOW
        subprocess.check_call(pip_cmd, **kwargs)
        import segno
        return segno
    except Exception:
        return None


def _print_qr_blocks(matrix, say, border=3):
    rows = [tuple(1 if cell else 0 for cell in row) for row in matrix]
    side = len(rows)
    pad = (0,) * border
    padded = []
    blank = (0,) * (side + border * 2)
    for _ in range(border):
        padded.append(blank)
    for row in rows:
        padded.append(pad + row + pad)
    for _ in range(border):
        padded.append(blank)
    if len(padded) % 2:
        padded.append(blank)
    full, upper, lower, empty = "█", "▀", "▄", " "
    style, reset = "\033[107;30m", "\033[0m"
    lines = []
    for i in range(0, len(padded), 2):
        top, bot = padded[i], padded[i + 1]
        chars = []
        for a, b in zip(top, bot):
            if a and b:
                chars.append(full)
            elif a:
                chars.append(upper)
            elif b:
                chars.append(lower)
            else:
                chars.append(empty)
        lines.append("".join(chars))
    try:
        for line in lines:
            say(style + line + reset)
    except UnicodeEncodeError:
        say("当前控制台编码无法画出二维码，请打开同目录 remote-qr.png 用微信扫。")


def show_phone_qr(phone_url, say):
    _enable_win_console()
    segno = _load_segno()
    if segno is None:
        say("未安装 segno，无法生成二维码。可执行: pip install -r requirements.txt")
        say("  或手动在微信打开：{}".format(phone_url))
        return
    qr = segno.make(phone_url, error="m")
    png_path = os.path.join(_script_dir(), "remote-qr.png")
    try:
        qr.save(png_path, scale=5, border=4, dark="#000000", light="#ffffff")
    except Exception as exc:
        png_path = ""
        say("二维码图片写入失败：{}".format(exc))
    say("")
    say("微信扫一扫（不要扫 127.0.0.1）：")
    say("  {}".format(phone_url))
    matrix = getattr(qr, "matrix", None)
    if matrix is not None:
        _print_qr_blocks(matrix, say, border=3)
    else:
        try:
            qr.terminal(out=sys.stdout, compact=True)
        except Exception:
            pass
    if png_path:
        say("控制台码扫不清时，可手动打开：{}".format(png_path))
    say("扫不开：手机和电脑同一 Wi-Fi，防火墙放行 TCP 23333。")
    say("")


def serve_web(base_url, token, timeout, bind, port):
    server = ThreadingHTTPServer((bind, port), WebHandler)
    server.lx_base = base_url
    server.lx_token = token
    server.lx_timeout = timeout
    start_loop_watch(server)
    def say(msg):
        print(msg)
        sys.stdout.flush()

    say("网页遥控已启动")
    say("  页面版本 {}（左上角「洛雪遥控」旁边；没有请强刷或关掉微信再打开）".format(PAGE_VER))
    say("  本机：  http://127.0.0.1:{}".format(port))
    ips = lan_ips()
    if ips:
        for ip in ips:
            say("  手机：  http://{}:{}".format(ip, port))
        show_phone_qr("http://{}:{}".format(ips[0], port), say)
    else:
        say("  手机：  http://<这台电脑的局域网IP>:{}".format(port))
        say("未检测到局域网 IP，无法生成微信二维码（不要用 127.0.0.1）。")
    say("  代理洛雪：{}".format(base_url))
    if "127.0.0.1" not in base_url and "localhost" not in base_url:
        say("  洛雪若就在这台电脑，可用 --host 127.0.0.1（不必勾选局域网访问）")
    say("电脑和手机同一 Wi-Fi；防火墙放行 TCP {}。Ctrl+C 停止。".format(port))
    if getattr(server, "lx_loop_one", False):
        say("  单曲循环：开（结尾回开头；遥控切歌后跟新曲）")
    health_check(base_url, token, timeout)
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.lx_loop_stop = True
        server.server_close()
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description="洛雪音乐 Open API 控制端")
    parser.add_argument(
        "command",
        nargs="?",
        help="next/prev/play/pause/toggle/status/volume/mute/seek/lyric，省略则进入交互",
    )
    parser.add_argument("cmd_args", nargs="*", help="命令参数，如 volume 50、seek 30、mute off")
    parser.add_argument(
        "--host",
        default=None,
        help="洛雪 Open API 主机。命令行默认 192.168.31.169；--web 未指定时默认 127.0.0.1，或 LX_API_HOST",
    )
    parser.add_argument("--port", type=int, default=None, help="默认 23330，或环境变量 LX_API_PORT")
    parser.add_argument("--url", default=None, help="完整基址，如 http://192.168.31.169:23330，或 LX_API_URL")
    parser.add_argument(
        "--token",
        default=None,
        help="可选。官方开放 API 无密钥；仅当你前面有反代/网关时再设，也可用 LX_API_TOKEN",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="对话超时秒数，默认 5")
    parser.add_argument("--keys", action="store_true", help="Windows 单键热键循环（n/p/空格/s/q）")
    parser.add_argument("--web", action="store_true", help="启动手机网页遥控（本机代理洛雪 API）")
    parser.add_argument("--web-port", type=int, default=None, help="网页端口，默认 23333，或 LX_WEB_PORT")
    parser.add_argument("--web-bind", default=None, help="网页监听地址，默认 0.0.0.0，或 LX_WEB_BIND")
    parser.add_argument(
        "--lx-exe",
        default=None,
        help="洛雪桌面端路径。也可用 LX_APP / lx_remote_state.json 的 lxExe",
    )
    parser.add_argument(
        "--lx-wait",
        type=float,
        default=None,
        help="自动启动后等待开放 API 的秒数，默认 40，或 LX_APP_WAIT",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="网页遥控不要自动启动洛雪桌面端",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    # 网页遥控未指定主机时连本机，避免默认局域网 IP 换网段后被当成远程而不自动启动
    if args.web and args.host is None and args.url is None:
        if not env_or("LX_API_HOST", "") and not env_or("LX_API_URL", ""):
            args.host = "127.0.0.1"
    base_url = build_base_url(args)
    token = args.token if args.token is not None else env_or("LX_API_TOKEN", "")
    token = token or None

    if args.web:
        bind = args.web_bind or env_or("LX_WEB_BIND", DEFAULT_WEB_BIND)
        port = args.web_port if args.web_port is not None else int(env_or("LX_WEB_PORT", DEFAULT_WEB_PORT))
        wait_raw = args.lx_wait if args.lx_wait is not None else env_or("LX_APP_WAIT", "")
        wait_s = float(wait_raw) if wait_raw not in (None, "") else DEFAULT_LAUNCH_WAIT
        base_url = ensure_local_lx(
            base_url,
            token,
            args.timeout,
            explicit_exe=args.lx_exe,
            wait_s=wait_s,
            launch=not args.no_launch,
        )
        return serve_web(base_url, token, args.timeout, bind, port)

    if args.command:
        key = ALIASES.get(args.command.lower())
        if not key or key in ("help", "quit", "exit"):
            if args.command.lower() in ("help", "-h"):
                print_help()
                return 0
            print("未知命令：{}".format(args.command), file=sys.stderr)
            print_help()
            return 2
        try:
            run_command(key, base_url, token, args.timeout, args=args.cmd_args)
        except Exception as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0

    if args.keys:
        hotkeys(base_url, token, args.timeout)
    else:
        repl(base_url, token, args.timeout)
    return 0


if __name__ == "__main__":
    _configure_stdio()
    sys.exit(main())
