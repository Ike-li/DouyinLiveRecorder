"""端到端测试: 拉流中途断开后要尽快重新录制, ffmpeg 的输出要写进 logs/ffmpeg.log.

在临时目录里复制一份程序, 用本地假 CDN 当"自定义录制直播"的 FLV 源:
第一次连接播放 8 秒后被重置(模拟断流), 之后的连接正常播放.
需要 ffmpeg 和 ffprobe, 整个用例大约 1~2 分钟.

运行: uv run python -m unittest discover -s tests -v
"""
import http.server
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROGRAM_FILES = ["main.py", "msg_push.py", "ffmpeg_install.py", "i18n.py", "i18n", "src"]
CUT_AFTER_SECONDS = 8
# 修复前断流后要等满一个循环时间(这里配置为300秒)才会重新拉流
RESTART_DEADLINE_SECONDS = 75

CONFIG = """[录制设置]
language(zh_cn/en) = zh_cn
是否跳过代理检测(是/否) = 是
视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频 = ts
原画|超清|高清|标清|流畅 = 原画
是否使用代理ip(是/否) = 否
循环时间(秒) = 300
分段录制是否开启 = 是
视频分段时间(秒) = 1800
录制完成后自动转为mp4格式 = 是
追加格式后删除原文件 = 是
"""


def make_source_flv(path: Path, seconds: int) -> None:
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-g", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-f", "flv", str(path),
    ], check=True)


def read_flv_tags(path: Path) -> tuple[bytes, list[tuple[float, bytes]]]:
    data = path.read_bytes()
    header_len = struct.unpack(">I", data[5:9])[0]
    header, pos, tags = data[:header_len + 4], header_len + 4, []
    while pos + 11 <= len(data):
        size = int.from_bytes(data[pos + 1:pos + 4], "big")
        timestamp = int.from_bytes(data[pos + 4:pos + 7], "big") | (data[pos + 7] << 24)
        end = pos + 11 + size + 4
        tags.append((timestamp / 1000, data[pos:end]))
        pos = end
    return header, tags


def kill_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def probe_duration(path: Path) -> float:
    output = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(output) if output else 0.0


class FakeLiveCDN:
    """按真实时间推送 FLV(chunked), 第一次连接播放 CUT_AFTER_SECONDS 秒后用 RST 断开."""

    def __init__(self, source: Path):
        self.header, self.tags = read_flv_tags(source)
        self.events: list[tuple[float, str]] = []
        self.request_count = 0
        self.lock = threading.Lock()
        cdn = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                with cdn.lock:
                    cdn.request_count += 1
                    number = cdn.request_count
                cdn.record("request")
                self.send_response(200)
                self.send_header("Content-Type", "video/x-flv")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                start = time.monotonic()
                try:
                    self.write_chunk(cdn.header)
                    for timestamp, tag in cdn.tags:
                        if number == 1 and timestamp >= CUT_AFTER_SECONDS:
                            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                            self.close_connection = True
                            cdn.record("cut")
                            return
                        delay = timestamp - (time.monotonic() - start)
                        if delay > 0:
                            time.sleep(delay)
                        self.write_chunk(tag)
                    self.wfile.write(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    cdn.record("client_left")

            def write_chunk(self, payload: bytes):
                self.wfile.write(b"%x\r\n" % len(payload) + payload + b"\r\n")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/live.flv"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def record(self, event: str) -> None:
        with self.lock:
            self.events.append((time.monotonic(), event))

    def times(self, event: str) -> list[float]:
        with self.lock:
            return [t for t, e in self.events if e == event]

    def wait_for(self, event: str, count: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.times(event)) >= count:
                return True
            time.sleep(0.5)
        return False


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg 和 ffprobe")
@unittest.skipIf(os.name == "nt", "用到了 POSIX 进程组")
class StreamDropTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = Path(tempfile.mkdtemp(prefix="dlr_e2e_"))
        cls.addClassCleanup(shutil.rmtree, cls.workdir, ignore_errors=True)
        for name in PROGRAM_FILES:
            source = PROJECT_ROOT / name
            if source.is_dir():
                shutil.copytree(source, cls.workdir / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(source, cls.workdir / name)

        flv = cls.workdir / "source.flv"
        make_source_flv(flv, seconds=60)
        cls.cdn = FakeLiveCDN(flv)
        cls.addClassCleanup(cls.cdn.server.server_close)
        cls.addClassCleanup(cls.cdn.server.shutdown)

        config_dir = cls.workdir / "config"
        config_dir.mkdir()
        (config_dir / "config.ini").write_text(CONFIG, encoding="utf-8-sig")
        cls.url_line = f"{cls.cdn.url},主播: e2e"
        cls.url_config = config_dir / "URL_config.ini"
        cls.url_config.write_text(cls.url_line + "\n", encoding="utf-8-sig")

        output = open(cls.workdir / "program_output.log", "w")
        cls.addClassCleanup(output.close)
        program = subprocess.Popen(
            [sys.executable, "main.py"], cwd=cls.workdir, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        cls.addClassCleanup(program.wait)
        cls.addClassCleanup(kill_process_group, program.pid)

        cls.cdn.wait_for("cut", 1, timeout=60)
        if cls.cdn.wait_for("request", 2, timeout=RESTART_DEADLINE_SECONDS):
            time.sleep(10)
        cls.url_config.write_text("#" + cls.url_line + "\n", encoding="utf-8-sig")
        cls.cdn.wait_for("client_left", 1, timeout=20)
        time.sleep(5)

        ffmpeg_log = cls.workdir / "logs" / "ffmpeg.log"
        cls.ffmpeg_log = ffmpeg_log.read_text(encoding="utf-8") if ffmpeg_log.exists() else ""
        cls.mp4_durations = [probe_duration(p) for p in sorted((cls.workdir / "downloads").rglob("*.mp4"))]
        cls.program_tail = "".join(
            (cls.workdir / "program_output.log").read_text(errors="replace").splitlines(keepends=True)[-20:]
        )

    def test_reconnects_within_a_minute_after_drop(self):
        cuts, requests = self.cdn.times("cut"), self.cdn.times("request")
        self.assertTrue(cuts, f"假 CDN 没有断开过连接, 程序可能没跑起来:\n{self.program_tail}")
        self.assertGreaterEqual(len(requests), 2, f"断流后 {RESTART_DEADLINE_SECONDS} 秒内没有重新拉流")
        self.assertLess(requests[1] - cuts[0], 60)

    def test_ffmpeg_errors_are_written_to_log(self):
        self.assertIn("开始录制", self.ffmpeg_log)
        self.assertIn("Error during demuxing", self.ffmpeg_log)
        self.assertIn("ffmpeg退出, 返回码: 0", self.ffmpeg_log)

    def test_stop_by_commenting_out_is_logged(self):
        self.assertIn("录制时被注释或程序退出", self.ffmpeg_log)

    def test_dropped_recording_is_still_converted_to_mp4(self):
        self.assertTrue(
            any(abs(d - CUT_AFTER_SECONDS) < 2 for d in self.mp4_durations),
            f"没有找到断流前那段约 {CUT_AFTER_SECONDS} 秒的 mp4, 实际: {self.mp4_durations}",
        )


if __name__ == "__main__":
    unittest.main()
