# -*- coding: utf-8 -*-
"""录制状态的人话提示: 把 ffmpeg 的退出原因翻译出来, 以及拼出状态看板."""
import unicodedata

# (ffmpeg 输出里的关键字, 提示), 按顺序匹配第一个
FFMPEG_EXIT_HINTS = [
    ("timed out", "拉流超时({timeout}秒没收到数据)"),
    ("Connection reset by peer", "连接被服务器重置"),
    ("Server returned 404", "流地址已失效(404)"),
    ("Server returned 403", "服务器拒绝访问(403)"),
    ("Invalid data found when processing input", "收到的数据无法解析"),
]


def explain_ffmpeg_exit(output: str, return_code: int, timeout_seconds: int) -> str:
    for keyword, hint in FFMPEG_EXIT_HINTS:
        if keyword in output:
            return hint.format(timeout=timeout_seconds)
    if return_code == 0:
        return "服务器结束了直播流"
    return f"ffmpeg异常退出(返回码{return_code})"


def display_width(text: str) -> int:
    # 中文等全角字符在终端里占两格
    return sum(2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1 for char in text)


def render_status(now: str, monitoring: int, recordings: list[tuple[str, str]],
                  events: list[tuple[str, str, str]], delay: int) -> str:
    """recordings 是 (主播名, 已录时长); events 是 (时间, 主播名, 内容), 按发生先后排列."""
    lines = [f"{now}  监测 {monitoring} 个  录制 {len(recordings)} 个"]
    if recordings:
        name_width = max(display_width(name) for name, _ in recordings)
        for name, elapsed in recordings:
            lines.append(f"  {name}{' ' * (name_width - display_width(name))}  录制中 {elapsed}")
    elif monitoring:
        lines.append(f"  没有正在录制的直播, 每 {delay} 秒检测一次开播")
    else:
        lines.append("  没有正在监测的直播")
    if events:
        lines.append("最近事件")
        lines.extend(f"  {at} {name} {message}" for at, name, message in reversed(events))
    return "\n".join(lines)
