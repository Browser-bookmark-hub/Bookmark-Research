"""Terminal prompts with a clack-style rich mode and a plain numbered fallback."""

import contextlib
import getpass
import os
import re
import select as _select
import shutil
import unicodedata
import threading
import time as _time
import warnings
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

try:
    import termios
except ImportError:  # pragma: no cover - Windows
    termios = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

# Windows console scan codes after a \x00/\xe0 prefix.
WINDOWS_KEYS = {"H": "up", "P": "down", "K": "left", "M": "right"}


def enable_windows_ansi():
    """Turn on VT escape processing for the Windows console; False if unavailable."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        return bool(kernel.GetConsoleMode(handle, ctypes.byref(mode))
                    and kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False

BAR = "│"
ACTIVE = "◆"
DONE = "◇"
ON = "◉"
OFF = "◯"
HIDE = "\x1b[?25l"
SHOW = "\x1b[?25h"


class Option:
    def __init__(self, value, label_en, label_zh=None, hint_en="", hint_zh=None, disabled=False, hint_always=False):
        self.value = value
        self.label_en = label_en
        self.label_zh = label_zh
        self.hint_en = hint_en
        self.hint_zh = hint_zh
        self.hint_always = hint_always
        self.disabled = disabled

    def __repr__(self):
        return "Option(%r)" % (self.value,)


class Prompter:
    def __init__(self, reader, writer, language="en", rich=None):
        self.reader = reader
        self.writer = writer
        self.language = language
        if rich is None:
            rich = (
                _isatty(reader)
                and _isatty(writer)
                and os.environ.get("TERM") != "dumb"
                and not os.environ.get("BOOKMARK_RESEARCH_PLAIN")
                and (termios is not None or msvcrt is not None)
                and enable_windows_ansi()
            )
        self.rich = bool(rich)
        self._fd = None

    # -- text helpers -------------------------------------------------
    def text(self, english, chinese=None):
        return chinese if self.language == "zh" and chinese is not None else english

    def _label(self, option):
        return self.text(option.label_en, option.label_zh)

    def _hint(self, option):
        return self.text(option.hint_en or "", option.hint_zh)

    def _color(self, code, value):
        if not self.rich or os.environ.get("NO_COLOR"):
            return value
        return "\x1b[%sm%s\x1b[0m" % (code, value)

    def _write(self, value):
        self.writer.write(value)
        self.writer.flush()

    def _line(self, value=""):
        self._write(value + "\n")

    @staticmethod
    def _width(value):
        plain = ANSI.sub("", value)
        return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in plain)

    def _fit(self, value):
        # Redraw moves up by line count, so a wrapped row would corrupt the frame.
        limit = _columns() - 1
        if self._width(value) <= limit:
            return value
        result, used = "", 0
        for token in re.split("(" + ANSI.pattern + ")", value):
            if ANSI.fullmatch(token):
                result += token
                continue
            for char in token:
                size = self._width(char)
                if used + size > limit - 1:
                    return result + "…\x1b[0m" if "\x1b[" in result else result + "…"
                result, used = result + char, used + size
        return result

    # -- output -------------------------------------------------------
    def say(self, english, chinese=None):
        message = self.text(english, chinese)
        if not self.rich:
            self._line(message)
            return
        for line in message.strip("\n").split("\n"):
            self._line("%s  %s" % (self._color("90", BAR), line))

    def intro(self, english, chinese=None):
        message = self.text(english, chinese)
        if self.rich:
            self._line(self._color("90", "┌") + "  " + self._color("1", message))
            self._line(self._color("90", BAR))
        else:
            self._line(message)

    def outro(self, english, chinese=None):
        message = self.text(english, chinese)
        if self.rich:
            self._line(self._color("90", BAR))
            self._line(self._color("90", "└") + "  " + message)
        else:
            self._line(message)

    def _mark(self, symbol, code, english, chinese):
        message = self.text(english, chinese)
        if self.rich:
            self._line("%s  %s" % (self._color(code, symbol), message))
        else:
            self._line("%s %s" % (symbol, message))

    def step(self, english, chinese=None):
        self._mark(DONE, "32", english, chinese)

    def success(self, english, chinese=None):
        self._mark("✓", "32", english, chinese)

    def warn(self, english, chinese=None):
        self._mark("!", "33", english, chinese)

    def error(self, english, chinese=None):
        self._mark("✗", "31", english, chinese)

    def note(self, title_en, title_zh, lines):
        title = self.text(title_en, title_zh)
        body = [self.text(en, zh) for en, zh in lines]
        if not self.rich:
            self._line(title)
            for item in body:
                self._line("  " + item)
            return
        width = max([self._width(title)] + [self._width(item) for item in body]) + 2
        self._line(self._color("90", BAR))
        if width + 6 > _columns():
            # Too wide for a box: keep the rail and let long paths wrap naturally.
            self._line("%s  %s" % (self._color("32", DONE), title))
            for item in body:
                self._line("%s  %s" % (self._color("90", BAR), item))
            return
        self._line("%s  %s %s╮" % (self._color("32", DONE), title, self._color("90", "─" * (width - self._width(title)))))
        for item in body:
            self._line("%s  %s%s%s" % (self._color("90", BAR), item, " " * (width - self._width(item) + 1), self._color("90", BAR)))
        self._line(self._color("90", "├" + "─" * (width + 3) + "╯"))

    @contextlib.contextmanager
    def spinner(self, english, chinese=None):
        message = self.text(english, chinese)
        if not self.rich:
            self._line(message)
            yield
            return
        stop = threading.Event()
        animate = _isatty(self.writer)

        def run():
            frames = "◒◐◓◑"
            index = 0
            while not stop.wait(0.1):
                index += 1
                self._write("\r\x1b[2K%s  %s" % (self._color("35", frames[index % 4]), message))

        self._write("%s  %s" % (self._color("35", "◒"), message))
        thread = threading.Thread(target=run, daemon=True) if animate else None
        if thread:
            thread.start()
        ok = False
        try:
            yield
            ok = True
        finally:
            stop.set()
            if thread:
                thread.join()
            symbol = self._color("32", "✓") if ok else self._color("31", "✗")
            self._write("\r\x1b[2K%s  %s\n" % (symbol, message))

    # -- plain input --------------------------------------------------
    def _readline(self, prompt):
        self._write(prompt)
        value = self.reader.readline()
        if value == "":
            raise KeyboardInterrupt
        return value.strip()

    # -- raw key input ------------------------------------------------
    @contextlib.contextmanager
    def _raw(self, hide=True):
        fd = None
        saved = None
        try:
            if termios is not None and _isatty(self.reader):
                fd = self.reader.fileno()
                saved = termios.tcgetattr(fd)
                # Not tty.setcbreak: its TCSAFLUSH discards keys typed ahead.
                attrs = termios.tcgetattr(fd)
                attrs[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
                attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 1, 0
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
                self._fd = fd
            elif termios is None and msvcrt is not None and _isatty(self.reader):
                self._fd = "msvcrt"
            if hide:
                self._write(HIDE)
            yield
        finally:
            self._fd = None
            if saved is not None:
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
            if hide:
                self._write(SHOW)

    def _char(self, timeout=None):
        if self._fd == "msvcrt":
            if timeout is not None:
                deadline = _time.monotonic() + timeout
                while not msvcrt.kbhit():
                    if _time.monotonic() >= deadline:
                        return None
                    _time.sleep(0.01)
            return msvcrt.getwch()
        if self._fd is not None:
            if timeout is not None and not _select.select([self._fd], [], [], timeout)[0]:
                return None
            data = os.read(self._fd, 1)
            return data.decode("latin-1") if data else ""
        return self.reader.read(1)

    def _readchar(self, timeout=None):
        if self._fd is None or self._fd == "msvcrt":
            return self._char(timeout)
        first = self._char(timeout)
        if not first or ord(first) < 0x80:
            return first
        raw = first.encode("latin-1")
        need = 1 if ord(first) >= 0xC0 else 0
        need = 3 if ord(first) >= 0xF0 else 2 if ord(first) >= 0xE0 else need
        for _ in range(need):
            more = self._char(0.05)
            if not more:
                break
            raw += more.encode("latin-1")
        return raw.decode("utf-8", "replace")

    def _key(self):
        char = self._readchar()
        if self._fd == "msvcrt" and char in ("\x00", "\xe0"):
            return WINDOWS_KEYS.get(self._readchar(), "other")
        if char == "" or char == "\x03" or char == "\x04":
            raise KeyboardInterrupt
        if char == "\x1b":
            nxt = self._readchar(0.05)
            if nxt not in ("[", "O"):
                raise KeyboardInterrupt
            final = self._readchar(0.05)
            while final and final in "0123456789;":
                final = self._readchar(0.05)
            return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(final or "", "other")
        if char in ("\r", "\n"):
            return "enter"
        if char in ("\x7f", "\x08"):
            return "backspace"
        return char

    def _redraw(self, lines, previous):
        if previous:
            self._write("\x1b[%dA\x1b[J" % previous)
        for line in lines:
            self._line(self._fit(line))
        return len(lines)

    def _collapse(self, previous, question, answer):
        if previous:
            self._write("\x1b[%dA\x1b[J" % previous)
        self._line("%s  %s %s %s" % (self._color("32", DONE), question, self._color("90", "·"), self._color("2", answer)))

    # -- list prompts -------------------------------------------------
    def _option_text(self, option):
        hint = self._hint(option)
        return "%s (%s)" % (self._label(option), hint) if hint else self._label(option)

    def _move(self, options, cursor, step):
        count = len(options)
        for offset in range(1, count + 1):
            index = (cursor + step * offset) % count
            if not options[index].disabled:
                return index
        return cursor

    def _render_list(self, question, options, cursor, chosen, multi, message=None):
        lines = ["%s  %s" % (self._color("36", ACTIVE), question)]
        for index, option in enumerate(options):
            hint = self._hint(option)
            if option.disabled:
                mark = OFF if multi else "○"
                row = self._color("2", "%s %s%s" % (mark, self._label(option), " (%s)" % hint if hint else ""))
            else:
                if multi:
                    mark = self._color("32", ON) if index in chosen else OFF
                else:
                    mark = self._color("32", "●") if index == cursor else "○"
                label = self._label(option)
                if index == cursor:
                    label = self._color("1", label)
                if hint and (index == cursor or option.hint_always):
                    label += " " + self._color("2", "(%s)" % hint)
                row = "%s %s" % (mark, label)
            lines.append("%s  %s" % (self._color("36", BAR), row))
        if message:
            lines.append("%s  %s" % (self._color("33", "▲"), self._color("33", message)))
        else:
            lines.append(self._color("36", "└"))
        return lines

    def _index_of(self, options, value):
        for index, option in enumerate(options):
            if option.value == value and not option.disabled:
                return index
        return None

    def _lookup(self, options, token):
        if token.isdigit() and 1 <= int(token) <= len(options):
            index = int(token) - 1
        else:
            index = next((i for i, o in enumerate(options) if str(o.value) == token), None)
        if index is None or options[index].disabled:
            return None
        return index

    def _print_numbered(self, question, options):
        self._line(question)
        for number, option in enumerate(options, 1):
            text = self._option_text(option)
            if option.disabled:
                text += " " + self.text("[unavailable]", "[不可用]")
            self._line("  %d. %s" % (number, text))

    def select(self, english, chinese, options, default=None):
        options = list(options)
        question = self.text(english, chinese)
        enabled = [i for i, o in enumerate(options) if not o.disabled]
        if not enabled:
            raise ValueError("No selectable options")
        start = self._index_of(options, default)
        if start is None:
            start = enabled[0]
        if not self.rich:
            self._print_numbered(question, options)
            while True:
                token = self._readline(self.text("Choose [%d]: ", "请选择 [%d]: ") % (start + 1))
                if not token:
                    return options[start].value
                index = self._lookup(options, token)
                if index is not None:
                    return options[index].value
                self._line(self.text("Enter a listed number or name.", "请输入列表中的序号或名称。"))
        cursor = start
        drawn = 0
        with self._raw():
            while True:
                drawn = self._redraw(self._render_list(question, options, cursor, (), False), drawn)
                key = self._key()
                if key in ("up", "k"):
                    cursor = self._move(options, cursor, -1)
                elif key in ("down", "j"):
                    cursor = self._move(options, cursor, 1)
                elif key == "enter":
                    self._collapse(drawn, question, self._label(options[cursor]))
                    return options[cursor].value

    def multiselect(self, english, chinese, options, defaults=(), required=True):
        options = list(options)
        question = self.text(english, chinese)
        chosen = set(i for i in (self._index_of(options, v) for v in defaults) if i is not None)
        enabled = [i for i, o in enumerate(options) if not o.disabled]
        if not self.rich:
            self._print_numbered(question, options)
            shown = ",".join(str(i + 1) for i in sorted(chosen)) or "-"
            prompt = self.text(
                "Choose numbers or names, comma-separated [%s]: ",
                "请输入序号或名称，用逗号分隔 [%s]: ",
            ) % shown
            while True:
                raw = self._readline(prompt)
                if not raw:
                    picked = set(chosen)
                elif raw == "-":
                    picked = set()
                else:
                    tokens = [t.strip() for t in raw.replace("，", ",").split(",") if t.strip()]
                    indexes = [self._lookup(options, t) for t in tokens]
                    if None in indexes:
                        self._line(self.text("Enter a listed number or name.", "请输入列表中的序号或名称。"))
                        continue
                    picked = set(indexes)
                if required and not picked:
                    self._line(self.text("Select at least one option.", "请至少选择一项。"))
                    continue
                return [options[i].value for i in sorted(picked)]
        cursor = enabled[0] if enabled else 0
        message = None
        drawn = 0
        with self._raw():
            while True:
                lines = self._render_list(question, options, cursor, chosen, True, message)
                if not message:
                    lines[-1] = "%s  %s" % (self._color("36", "└"), self._color("2", self.text(
                        "space toggle · a all · enter confirm", "空格 切换 · a 全选 · 回车 确认")))
                drawn = self._redraw(lines, drawn)
                key = self._key()
                message = None
                if key in ("up", "k"):
                    cursor = self._move(options, cursor, -1)
                elif key in ("down", "j"):
                    cursor = self._move(options, cursor, 1)
                elif key == " ":
                    if enabled and not options[cursor].disabled:
                        chosen ^= {cursor}
                elif key == "a":
                    chosen = set() if all(i in chosen for i in enabled) else set(enabled)
                elif key == "enter":
                    if required and not chosen:
                        message = self.text("Select at least one option.", "请至少选择一项。")
                        continue
                    values = [options[i] for i in sorted(chosen)]
                    answer = ", ".join(self._label(o) for o in values) or self.text("(none)", "（无）")
                    self._collapse(drawn, question, answer)
                    return [o.value for o in values]

    def confirm(self, english, chinese, default=True):
        question = self.text(english, chinese)
        if not self.rich:
            suffix = "[Y/n]" if default else "[y/N]"
            while True:
                raw = self._readline("%s %s: " % (question, suffix)).lower()
                if not raw:
                    return default
                if raw in ("y", "yes", "是", "1"):
                    return True
                if raw in ("n", "no", "否", "2"):
                    return False
                self._line(self.text("Please answer y or n.", "请输入 y 或 n。"))
        yes, no = self.text("Yes", "是"), self.text("No", "否")
        value = default
        drawn = 0
        with self._raw():
            while True:
                marks = [
                    (self._color("32", "●") + " " + yes) if value else ("○ " + self._color("2", yes)),
                    (self._color("32", "●") + " " + no) if not value else ("○ " + self._color("2", no)),
                ]
                lines = [
                    "%s  %s" % (self._color("36", ACTIVE), question),
                    "%s  %s / %s" % (self._color("36", BAR), marks[0], marks[1]),
                    self._color("36", "└"),
                ]
                drawn = self._redraw(lines, drawn)
                key = self._key()
                if key in ("left", "right", "up", "down", "h", "l", "k", "j", "\t"):
                    value = not value
                elif key in ("y", "Y"):
                    value = True
                elif key in ("n", "N"):
                    value = False
                elif key == "enter":
                    self._collapse(drawn, question, yes if value else no)
                    return value

    # -- text input ---------------------------------------------------
    def input(self, english, chinese, default="", validate=None):
        question = self.text(english, chinese)
        while True:
            if self.rich:
                value = self._rich_text(question, default, None, False)
            else:
                value = self._readline("%s [%s]: " % (question, default) if default else "%s: " % question)
            value = value or default
            problem = validate(value) if validate else None
            if not problem:
                if self.rich:
                    self._collapse(1, question, value)
                return value
            if self.rich:
                self._write("\x1b[1A\x1b[J")
            self._mark("✗" if self.rich else "!", "31", problem[0], problem[1])

    def password(self, english, chinese):
        question = self.text(english, chinese)
        if not self.rich:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    return getpass.getpass(question + ": ", stream=self.writer)
                except getpass.GetPassWarning:
                    raise ValueError(
                        "Cannot hide terminal input; configure the API key in the host environment instead"
                    ) from None
        value = self._rich_text(question, "", "•", True)
        answer = "••••••" if value else self.text("(skipped)", "（已跳过）")
        self._collapse(1, question, answer)
        return value

    def _rich_text(self, question, default, mask, secret):
        buffer = []
        placeholder = self._color("2", default) if default else ""
        with self._raw(hide=False):
            self._write("%s  %s: %s" % (self._color("36", ACTIVE), question, placeholder))
            if default:
                self._write("\x1b[%dD" % len(default))
            try:
                while True:
                    key = self._key()
                    if key == "enter":
                        break
                    if key == "backspace":
                        if buffer:
                            buffer.pop()
                            self._write("\x08 \x08")
                        continue
                    if len(key) != 1 or key < " ":
                        continue
                    if not buffer and default:
                        self._write("\x1b[K")
                    buffer.append(key)
                    self._write(mask if mask else key)
            finally:
                self._write("\n")
        return "".join(buffer)


def _columns():
    # Unsized pseudo-terminals report 0 columns; treat that like an unknown size.
    columns = shutil.get_terminal_size((80, 24)).columns
    return columns if columns > 0 else 80


def _isatty(stream):
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False
