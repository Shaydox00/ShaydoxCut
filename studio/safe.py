"""Small helpers for what is safe to show a user."""
import re

_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]*[\\/][^\s'\"]+")


def friendly(e, limit=600) -> str:
    """An error message for the user: trimmed, with any server file paths removed. A missing ffmpeg, which Windows
    reports only as "the system cannot find the file specified", is said in plain words with what to do."""
    from . import tools
    text = re.sub(r"\[[0-9;]*[A-Za-z]|\[0;3\dm|\[0m", "", str(e))      # colour codes from download tools
    if "10054" in text or "forcibly closed" in text or "Connection reset" in text:
        return "The connection to the video site dropped several times while downloading. Check your internet and try again."
    return tools.explain(e) or _PATH.sub("[file]", text[-limit:])

