"""Layout invariants: the interface must never overflow, at any size."""

import unittest

from core import utils, view
from core.direction import Direction
from core.theme import Layout

SIZES = [(24, 6), (32, 8), (36, 14), (40, 12), (45, 20), (51, 24),
         (52, 24), (80, 24), (89, 30), (100, 40), (102, 50)]

D = Direction("en", "pl")
HISTORY = [
    {"kind": "exchange", "direction": D, "detected": None,
     "input": "Hello, how are you doing today my dear friend?",
     "output": "Cześć, jak się dzisiaj masz mój drogi przyjacielu?"},
    {"kind": "error", "message": "Could not reach translation endpoint: offline."},
    {"kind": "exchange", "direction": Direction("auto", "ja"),
     "detected": "en", "input": "good morning",
     "output": "おはようございます、今日はとても良い天気ですね"},
    {"kind": "exchange", "direction": D, "detected": None,
     "input": "a" * 300, "output": "b" * 300},   # unbreakable token
]


class FrameInvariants(unittest.TestCase):
    def setUp(self):
        self._tty = utils._IS_TTY
        utils._IS_TTY = True          # exercise the ANSI-heavy code path
        import os
        os.environ["TRNS_COLOR"] = "1"

    def tearDown(self):
        utils._IS_TTY = self._tty
        import os
        os.environ.pop("TRNS_COLOR", None)

    def frames(self):
        for cols, rows in SIZES:
            for hist in ([], HISTORY):
                for off in (0, 3, 999):
                    lay = Layout(cols, rows)
                    yield lay, view.render_frame(lay, D, hist, scroll_offset=off)

    def test_line_count_leaves_room_for_input_row(self):
        for lay, f in self.frames():
            self.assertEqual(len(f.lines), lay.rows - 1, lay)

    def test_no_line_is_wider_than_the_screen(self):
        for lay, f in self.frames():
            for n, line in enumerate(f.lines, 1):
                w = view.visible_width(line)
                self.assertLessEqual(w, lay.cols, f"{lay} row {n}: {line!r}")

    def test_hits_are_on_screen(self):
        for lay, f in self.frames():
            for h in f.hits:
                self.assertGreaterEqual(h.row0, 1)
                self.assertLess(h.row1, lay.rows, "hit must not cover input row")
                self.assertGreaterEqual(h.x0, 1)
                self.assertLessEqual(h.x1, lay.cols)

    def test_language_chip_is_tappable_everywhere(self):
        for lay, f in self.frames():
            hit = view.hit_at(f.hits, lay.cols - 3, 1)
            self.assertIsNotNone(hit, lay)
            self.assertEqual(hit.action, "swap")

    def test_footer_actions_present_when_there_is_room(self):
        lay = Layout(40, 16)
        f = view.render_frame(lay, D, [])
        actions = {h.action for h in f.hits}
        self.assertTrue({"swap", "copy", "settings"} <= actions)

    def test_footer_hidden_on_very_short_screens(self):
        lay = Layout(40, 8)
        self.assertFalse(lay.show_footer)
        f = view.render_frame(lay, D, [])
        self.assertEqual(sum(h.action == "settings" for h in f.hits), 0)

    def test_card_tap_targets_point_at_their_entry(self):
        lay = Layout(60, 30)
        f = view.render_frame(lay, D, HISTORY[:1])
        copies = [h for h in f.hits if h.action == "copy" and h.row0 == h.row1
                  and h.row0 >= lay.history_top]
        self.assertTrue(copies)
        self.assertTrue(all(h.arg == 0 for h in copies))

    def test_toast_replaces_action_bar(self):
        lay = Layout(40, 16)
        f = view.render_frame(lay, D, [], toast=("copied", "ok"))
        self.assertIn("copied", f.lines[lay.footer_row - 1])
        self.assertFalse([h for h in f.hits if h.action == "copy"])

    def test_scroll_indicator(self):
        lay = Layout(40, 12)
        f = view.render_frame(lay, D, HISTORY, scroll_offset=4)
        self.assertIn("newer", f.lines[lay.bottom_rule_row - 1])


class NoColour(unittest.TestCase):
    def test_plain_output_has_no_escape_codes(self):
        old = utils._IS_TTY
        utils._IS_TTY = False
        try:
            f = view.render_frame(Layout(40, 16), D, HISTORY)
            self.assertFalse(any("\x1b" in ln for ln in f.lines))
        finally:
            utils._IS_TTY = old


class TextPrimitives(unittest.TestCase):
    def test_wrap_respects_width_and_wide_chars(self):
        for text in ("hello world " * 20, "日本語のテキスト" * 8, "x" * 100):
            for width in (5, 10, 33):
                for ln in view.wrap(text, width):
                    self.assertLessEqual(view.visible_width(ln), max(4, width))

    def test_wrap_keeps_paragraphs(self):
        self.assertEqual(view.wrap("a\n\nb", 10), ["a", "", "b"])

    def test_truncate(self):
        self.assertLessEqual(view.visible_width(view.truncate("x" * 50, 10)), 10)
        self.assertEqual(view.truncate("short", 10), "short")

    def test_match_languages(self):
        codes = list(utils.LANGUAGES)
        self.assertEqual(view.match_languages("pol", codes)[0], "pl")
        self.assertIn("zh-cn", view.match_languages("chin", codes))
        self.assertEqual(view.match_languages("", codes), codes)
        self.assertEqual(view.match_languages("zzzz", codes), [])

    def test_language_grid_columns_adapt(self):
        codes = ["en", "pl", "de", "fr", "es", "it", "pt", "nl"]
        narrow = view.language_grid(codes, 30)
        wide = view.language_grid(codes, 100)
        self.assertEqual(len(narrow), len(codes))       # 1 column
        self.assertLess(len(wide), len(narrow))          # several columns


class LayoutBreakpoints(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(Layout(40, 20).mode, "compact")
        self.assertEqual(Layout(60, 20).mode, "regular")
        self.assertEqual(Layout(120, 20).mode, "wide")


if __name__ == "__main__":
    unittest.main()
