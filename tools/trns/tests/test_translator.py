import json
import unittest
from unittest import mock

from core import translator


class Unwrap(unittest.TestCase):
    def test_joins_sentences_and_detects_language(self):
        payload = [[["Cześć ", "Hello ", None, None, 10], ["świecie", "world"]],
                   None, "en"]
        self.assertEqual(translator._unwrap(payload), ("Cześć świecie", "en"))

    def test_skips_empty_chunks(self):
        self.assertEqual(translator._unwrap([[[], None, ["ok"]], None, None]),
                         ("ok", None))

    def test_malformed_payload(self):
        with self.assertRaises(translator.TranslationError):
            translator._unwrap(None)


class Translate(unittest.TestCase):
    def test_empty_and_same_language_skip_network(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            self.assertEqual(translator.translate("  ", "en", "pl").text, "")
            self.assertEqual(translator.translate("hi", "en", "en").text, "hi")
            urlopen.assert_not_called()

    def test_length_limit(self):
        with self.assertRaises(translator.TranslationError):
            translator.translate("x" * (translator.MAX_CHARS + 1), "en", "pl")

    def test_happy_path(self):
        body = json.dumps([[["Cześć", "Hello"]], None, "en"]).encode()
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = body
        with mock.patch("urllib.request.urlopen", return_value=resp):
            r = translator.translate("Hello", "auto", "pl")
        self.assertEqual((r.text, r.detected_source_lang), ("Cześć", "en"))


if __name__ == "__main__":
    unittest.main()
