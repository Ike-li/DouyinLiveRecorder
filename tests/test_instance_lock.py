"""instance_lock 的单元测试: 这台电脑上同时只运行一个录制程序.
新的 douyin-live-recorder 也锁同一个文件 ~/.douyin-recorder.lock, 两个同时跑会把同一场直播录两遍.

运行: uv run python -m unittest discover -s tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import instance_lock  # noqa: E402


@unittest.skipIf(os.name == 'nt', "用 flock 模拟另一个程序")
class MachineLockTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_refused_while_another_recorder_holds_the_lock(self):
        import fcntl

        other = open(self.home / ".douyin-recorder.lock", "a")
        self.addCleanup(other.close)
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertIsNone(instance_lock.acquire_machine_lock())

    def test_main_exits_before_importing_src(self):
        # 只放 main.py 和 instance_lock.py: 要在 import src 之前就退出, 导入 src 会执行 check_node(), 可能自动安装 Node.js
        import fcntl

        for name in ("main.py", "instance_lock.py"):
            shutil.copy2(PROJECT_ROOT / name, self.home / name)
        other = open(self.home / ".douyin-recorder.lock", "a")
        self.addCleanup(other.close)
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run([sys.executable, "main.py"], cwd=self.home, stdin=subprocess.DEVNULL,
                                capture_output=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("另一个录制程序", result.stderr)

    def test_free_again_once_the_running_recorder_exits(self):
        running = instance_lock.acquire_machine_lock()
        self.assertIsNotNone(running)
        self.assertIsNone(instance_lock.acquire_machine_lock())
        running.close()
        again = instance_lock.acquire_machine_lock()
        self.assertIsNotNone(again)
        again.close()


if __name__ == "__main__":
    unittest.main()
