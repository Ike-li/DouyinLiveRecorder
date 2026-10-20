# -*- encoding: utf-8 -*-
"""这台电脑上同时只运行一个录制程序.

新的 douyin-live-recorder 也锁同一个文件 ~/.douyin-recorder.lock: 两个程序同时跑会把同一场直播录两遍.
锁随进程退出自动释放, 被强杀也一样. 放在 src 外面: 导入 src 会执行 check_node(), 可能自动安装 Node.js.
"""
import os
from pathlib import Path
from typing import IO, Optional

if os.name == 'nt':
    import msvcrt
else:
    import fcntl

MACHINE_LOCK_NAME = '.douyin-recorder.lock'
OTHER_RECORDER_HINT = (f"这台电脑上已经有另一个录制程序在运行(新的 douyin-live-recorder, 或另一份 DouyinLiveRecorder; "
                       f"它们都锁 ~/{MACHINE_LOCK_NAME}), 同时运行会把同一场直播录两遍")


def acquire_machine_lock() -> Optional[IO]:
    """返回要一直拿着的锁文件; 已经有一个录制程序在运行时返回 None."""
    lock_file = open(Path.home() / MACHINE_LOCK_NAME, 'a')
    try:
        if os.name == 'nt':
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file
