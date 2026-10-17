"""record_status 的单元测试: ffmpeg 的退出原因翻译成人话, 以及状态看板的排版.

运行: uv run python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from record_status import display_width, explain_ffmpeg_exit, render_status  # noqa: E402

# 以下 ffmpeg 输出都取自实际运行
TIMEOUT_OUTPUT = "[in#0/flv @ 0x7feb9d805400] Error during demuxing: Operation timed out\n"
RESET_OUTPUT = "[in#0/flv @ 0x14a607760] Error during demuxing: Connection reset by peer\n"
NOT_FOUND_OUTPUT = (
    "[in#0 @ 0x133605040] Error opening input: Server returned 404 Not Found\n"
    "Error opening input file http://127.0.0.1:18099/nope.flv.\n"
    "Error opening input files: Server returned 404 Not Found\n"
)
FORBIDDEN_OUTPUT = (
    "[in#0 @ 0x14c604940] Error opening input: Server returned 403 Forbidden (access denied)\n"
    "Error opening input file http://127.0.0.1:60117/live.flv.\n"
    "Error opening input files: Server returned 403 Forbidden (access denied)\n"
)
INVALID_DATA_OUTPUT = "[in#0/flv @ 0x153104080] Error during demuxing: Invalid data found when processing input\n"


class ExplainFfmpegExitTest(unittest.TestCase):
    def test_read_timeout(self):
        self.assertEqual(explain_ffmpeg_exit(TIMEOUT_OUTPUT, 0, timeout_seconds=15), "拉流超时(15秒没收到数据)")

    def test_read_timeout_with_linux_wording(self):
        output = TIMEOUT_OUTPUT.replace("Operation timed out", "Connection timed out")
        self.assertEqual(explain_ffmpeg_exit(output, 0, timeout_seconds=15), "拉流超时(15秒没收到数据)")

    def test_connection_reset(self):
        self.assertEqual(explain_ffmpeg_exit(RESET_OUTPUT, 0, timeout_seconds=15), "连接被服务器重置")

    def test_stream_url_gone(self):
        self.assertEqual(explain_ffmpeg_exit(NOT_FOUND_OUTPUT, 8, timeout_seconds=15), "流地址已失效(404)")

    def test_access_denied(self):
        self.assertEqual(explain_ffmpeg_exit(FORBIDDEN_OUTPUT, 8, timeout_seconds=15), "服务器拒绝访问(403)")

    def test_corrupted_data(self):
        self.assertEqual(explain_ffmpeg_exit(INVALID_DATA_OUTPUT, 0, timeout_seconds=15), "收到的数据无法解析")

    def test_server_closed_stream_without_error(self):
        self.assertEqual(explain_ffmpeg_exit("", 0, timeout_seconds=15), "服务器结束了直播流")

    def test_unrecognized_failure_keeps_return_code(self):
        self.assertEqual(explain_ffmpeg_exit("something odd\n", 1, timeout_seconds=15), "ffmpeg异常退出(返回码1)")


RECORDINGS = [("ABC(测试主播)", "0:46:45"), ("某个测试主播小号", "0:46:45")]


class RenderStatusTest(unittest.TestCase):
    def test_header_is_one_short_line(self):
        text = render_status("13:57:38", 4, RECORDINGS, [], delay=300)
        self.assertEqual(text.splitlines()[0], "13:57:38  监测 4 个  录制 2 个")

    def test_recording_column_is_aligned(self):
        lines = render_status("13:57:38", 4, RECORDINGS, [], delay=300).splitlines()[1:3]
        self.assertEqual(len({display_width(line.split("录制中")[0]) for line in lines}), 1, lines)

    def test_no_separator_lines_or_static_settings(self):
        text = render_status("13:57:38", 4, RECORDINGS, [], delay=300)
        for noise in ("xxxxxxxx", "录制视频格式", "瞬时错误", "同一时间访问网络的线程数"):
            self.assertNotIn(noise, text)

    def test_recent_events_newest_first(self):
        events = [("13:10:54", "测试主播-甲", "开始录制"), ("13:17:52", "测试主播-甲", "录制结束: 主播已下播")]
        lines = render_status("13:57:38", 4, RECORDINGS, events, delay=300).splitlines()
        start = lines.index("最近事件")
        self.assertEqual([line.split()[0] for line in lines[start + 1:]], ["13:17:52", "13:10:54"])

    def test_idle_message_mentions_check_interval(self):
        text = render_status("13:57:38", 4, [], [], delay=300)
        self.assertIn("没有正在录制的直播", text)
        self.assertIn("300", text)

    def test_nothing_monitored(self):
        self.assertIn("没有正在监测的直播", render_status("13:57:38", 0, [], [], delay=300))


if __name__ == "__main__":
    unittest.main()
