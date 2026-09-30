"""Keyboard/mouse pipeline: parser, line editor, tap dispatch."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from core import keys, ui, utils


def feed(*chunks):
    """Patch the raw byte source with a scripted sequence."""
    data = bytearray()
    for c in chunks:
        data += c.encode("utf-8") if isinstance(c, str) else c
    queue = list(data)

    def read_byte():
        if not queue:
            raise EOFError
        return bytes([queue.pop(0)])

    return mock.patch.object(keys, "_read_byte", read_byte)


def sgr(button, x, y, release=False):
    return f"\x1b[<{button};{x};{y}{'m' if release else 'M'}"


class EscapeParser(unittest.TestCase):
    def parse(self, seq):
        with feed(seq[1:]):
            return keys.read_escape()

    def test_arrows(self):
        self.assertEqual(self.parse("\x1b[A")[0], "up")
        self.assertEqual(self.parse("\x1b[D")[0], "left")
        self.assertEqual(self.parse("\x1bOH")[0], "home")

    def test_delete_key(self):
        self.assertEqual(self.parse("\x1b[3~")[0], "delete")

    def test_wheel_events_are_recognised(self):
        # Regression: these used to be swallowed as generic mouse events.
        self.assertEqual(self.parse(sgr(64, 5, 5))[0], "mouse_wheel_up")
        self.assertEqual(self.parse(sgr(65, 5, 5))[0], "mouse_wheel_down")

    def test_left_click(self):
        action, p = self.parse(sgr(0, 12, 3))
        self.assertEqual(action, "mouse_event")
        self.assertEqual((p["button"], p["x"], p["y"]), (0, 12, 3))
        self.assertFalse(p["release"])

    def test_utf8_input(self):
        with feed("ż"):
            self.assertEqual(keys.read_input_unit(), ("char", "ż"))


class PromptWindow(unittest.TestCase):
    def test_short_text_is_untouched(self):
        buf = list("hello")
        self.assertEqual(ui.prompt_window(buf, 5, 30), (0, 5, 0, 0))

    def test_long_text_never_exceeds_available_width(self):
        buf = list("word " * 40)
        for avail in (10, 20, 36):
            for cur in (0, 5, 100, len(buf)):
                s, e, lm, rm = ui.prompt_window(buf, cur, avail)
                shown = keys.buffered_width(buf[s:e]) + lm + rm
                self.assertLessEqual(shown, avail, (avail, cur))
                self.assertLessEqual(s, cur)
                self.assertGreaterEqual(e, cur)          # cursor stays visible

    def test_wide_characters_fit(self):
        buf = list("日本語" * 20)
        s, e, lm, rm = ui.prompt_window(buf, len(buf), 20)
        self.assertLessEqual(keys.buffered_width(buf[s:e]) + lm + rm, 20)


class LineEditor(unittest.TestCase):
    def setUp(self):
        self._p = [
            mock.patch.object(ui, "_terminal_size", lambda *a, **k: (40, 20)),
            mock.patch.object(utils, "_IS_TTY", False),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def run_editor(self, *chunks, **callbacks):
        buf = io.StringIO()
        with feed(*chunks), redirect_stdout(buf):
            result = ui._read_line_at_prompt(**callbacks)
        return result, buf.getvalue()

    def test_enter_returns_text(self):
        (text, cmd), _ = self.run_editor("hello\r")
        self.assertEqual((text, cmd), ("hello", None))

    def test_backspace_removes_one_character(self):
        (text, _), _ = self.run_editor("helx\x7flo\r")
        self.assertEqual(text, "hello")

    def test_ctrl_c_exits(self):
        self.assertEqual(self.run_editor("abc\x03")[0], (None, None))

    def test_tab_swaps_without_touching_text(self):
        calls = []
        (text, _), _ = self.run_editor(
            "abc\tdef\r", on_tab=lambda: calls.append(1))
        self.assertEqual(text, "abcdef")
        self.assertEqual(len(calls), 1)

    def test_cursor_editing_in_the_middle(self):
        (text, _), _ = self.run_editor("ac\x1b[Db\r")
        self.assertEqual(text, "abc")

    def test_delete_key(self):
        (text, _), _ = self.run_editor("abc\x1b[D\x1b[D\x1b[3~\r")
        self.assertEqual(text, "ac")

    def test_long_input_does_not_wrap_the_frame(self):
        """40 columns, 100 typed characters: no output line may exceed the
        screen (a wrapped input row scrolls the whole TUI on phones)."""
        _, out = self.run_editor("x" * 100 + "\r")
        # every redraw starts with a cursor-position escape; the text that
        # follows within one redraw must fit the width
        for chunk in out.split("\x1b[20;1H")[1:]:
            visible = chunk.split("\r")[0]
            plain = "".join(c for c in visible if c.isprintable())
            # strip CSI sequences roughly
            import re
            plain = re.sub(r"\[[0-9;]*[A-Za-z]", "", plain)
            self.assertLessEqual(len(plain), 40)

    def test_tap_on_action_returns_command_and_keeps_text(self):
        seen = []

        def on_click(x, y):
            seen.append((x, y))
            return "/settings"

        (text, cmd), _ = self.run_editor(
            "draft", sgr(0, 5, 3), on_click=on_click)
        self.assertEqual((text, cmd), ("draft", "/settings"))
        self.assertEqual(seen, [(5, 3)])

    def test_tap_that_hits_nothing_is_ignored(self):
        (text, cmd), _ = self.run_editor(
            "hi", sgr(0, 5, 3), "\r", on_click=lambda x, y: None)
        self.assertEqual((text, cmd), ("hi", None))

    def test_mouse_wheel_scrolls(self):
        actions = []
        self.run_editor(sgr(64, 3, 3), sgr(65, 3, 3), "\r",
                        on_scroll=actions.append)
        self.assertEqual(actions, ["mouse_wheel_up", "mouse_wheel_down"])

    def test_clicking_the_input_row_moves_the_cursor(self):
        # Row 20 is the input row; column 6 is the 3rd character (x = 4..).
        (text, _), _ = self.run_editor(
            "abcd", sgr(0, 6, 20), sgr(0, 6, 20, release=True), "X\r")
        self.assertEqual(text, "abXcd")


if __name__ == "__main__":
    unittest.main()
