"""Rich and plain terminal prompts."""

import io
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tui import Option, Prompter


OPTIONS = [
    Option("exa", "Exa", "Exa 搜索", hint_en="default", hint_zh="默认"),
    Option("parallel", "Parallel"),
    Option("jina", "Jina", hint_en="needs key", disabled=True),
    Option("tavily", "Tavily"),
]


def make(keys, rich, language="en"):
    out = io.StringIO()
    return Prompter(io.StringIO(keys), out, language=language, rich=rich), out


class PlainTests(unittest.TestCase):
    def test_select_number_name_default_and_invalid(self):
        p, out = make("\n", False)
        self.assertEqual(p.select("Pick", "选择", OPTIONS, default="parallel"), "parallel")
        self.assertIn("  1. Exa (default)", out.getvalue())
        self.assertIn("Choose [2]: ", out.getvalue())
        p, out = make("9\n3\ntavily\n", False)
        self.assertEqual(p.select("Pick", None, OPTIONS), "tavily")
        self.assertEqual(out.getvalue().count("Enter a listed number or name."), 2)

    def test_multiselect(self):
        p, _ = make("4,1\n", False)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS), ["exa", "tavily"])
        p, _ = make("\n", False)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS, defaults=("parallel", "jina")), ["parallel"])
        p, out = make("-\n2\n", False)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS), ["parallel"])
        self.assertIn("Select at least one", out.getvalue())
        p, _ = make("-\n", False)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS, required=False), [])

    def test_confirm_and_input(self):
        for keys, default, expected in [("\n", True, True), ("\n", False, False), ("是\n", False, True),
                                        ("2\n", True, False), ("maybe\nyes\n", False, True)]:
            p, _ = make(keys, False)
            self.assertEqual(p.confirm("Ok?", None, default=default), expected)
        p, out = make("\n", False)
        self.assertEqual(p.input("Name", None, default="x"), "x")
        self.assertIn("Name [x]: ", out.getvalue())
        p, out = make("bad\ngood\n", False)
        check = lambda v: ("Bad value", "错误") if v == "bad" else None
        self.assertEqual(p.input("Name", None, validate=check), "good")
        self.assertIn("Bad value", out.getvalue())

    def test_eof_cancels(self):
        p, _ = make("", False)
        with self.assertRaises(KeyboardInterrupt):
            p.select("Pick", None, OPTIONS)

    def test_plain_password_refuses_visible_input(self):
        import getpass
        p, _ = make("", False)

        def fake(prompt, stream=None):
            import warnings
            warnings.warn("echo", getpass.GetPassWarning)
            return "secret"

        with mock.patch("getpass.getpass", fake):
            with self.assertRaises(ValueError):
                p.password("Key", None)

    def test_chinese_labels(self):
        p, out = make("\n", False, "zh")
        self.assertEqual(p.select("Pick", "选择", OPTIONS), "exa")
        self.assertIn("1. Exa 搜索 (默认)", out.getvalue())
        self.assertIn("请选择 [1]: ", out.getvalue())

    def test_auto_rich_false_for_stringio(self):
        self.assertFalse(Prompter(io.StringIO(), io.StringIO()).rich)


class RichTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict("os.environ", {"NO_COLOR": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_select_moves_and_skips_disabled(self):
        p, out = make("\x1b[B \r", True)
        self.assertEqual(p.select("Pick", None, OPTIONS), "parallel")
        self.assertIn("◇  Pick", out.getvalue())
        self.assertIn("\x1b[?25h", out.getvalue())
        p, _ = make("\x1b[B\x1b[B\r", True)
        self.assertEqual(p.select("Pick", None, OPTIONS), "tavily")
        p, _ = make("k\r", True)
        self.assertEqual(p.select("Pick", None, OPTIONS), "tavily")
        p, _ = make("\x1bOA\r", True)
        self.assertEqual(p.select("Pick", None, OPTIONS, default="parallel"), "exa")

    def test_multiselect_toggle_all_and_required(self):
        p, _ = make("a\r", True)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS), ["exa", "parallel", "tavily"])
        p, out = make("\rj \r", True)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS), ["parallel"])
        self.assertIn("Select at least one", out.getvalue())
        p, _ = make("jj \r", True)
        self.assertEqual(p.multiselect("Pick", None, OPTIONS, defaults=("jina", "exa")), ["exa", "tavily"])

    def test_confirm_and_input(self):
        p, _ = make("\x1b[C\r", True)
        self.assertFalse(p.confirm("Ok?", None))
        p, _ = make("ab\x7fc\r", True)
        self.assertEqual(p.input("Name", None), "ac")

    def test_password_is_masked(self):
        p, out = make("s3cr3t\r", True)
        self.assertEqual(p.password("Key", None), "s3cr3t")
        self.assertNotIn("s3cr3t", out.getvalue())
        self.assertIn("••••••", out.getvalue())
        p, out = make("\r", True, "zh")
        self.assertEqual(p.password("Key", "密钥"), "")
        self.assertIn("（已跳过）", out.getvalue())

    def test_escape_and_eof_cancel(self):
        for keys in ("\x1b", "\x1bx", "", "\x03"):
            p, out = make(keys, True)
            with self.assertRaises(KeyboardInterrupt):
                p.select("Pick", None, OPTIONS)
            self.assertTrue(out.getvalue().endswith("\x1b[?25h"))

    def test_output_helpers(self):
        p, out = make("", True)
        p.say("hello")
        p.note("Title", None, [("line", "行")])
        with p.spinner("Working"):
            pass
        self.assertIn("│  hello", out.getvalue())
        self.assertIn("✓", out.getvalue())
        p, out = make("", False)
        with self.assertRaises(RuntimeError):
            with p.spinner("Work"):
                raise RuntimeError
        self.assertEqual(out.getvalue(), "Work\n")


if __name__ == "__main__":
    unittest.main()
