"""UTF-8 standard streams; Windows pipes otherwise use the ANSI code page."""

import sys


def utf8_stdio():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict" if stream is sys.stdin else "backslashreplace")
