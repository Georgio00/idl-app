"""
Tests for ocr_client._words_and_text_from_response — the function that
flattens a Google Cloud Vision document_text_detection response's
page/block/paragraph/word/symbol structure into the flat
list[OcrWord]/full_text shape every caller in this codebase (license_ocr,
passport_ocr, pipeline) actually works with.

2026-08-24 history: this file used to test ocr_client._run_tesseract's
word/line reconstruction from pytesseract's flat image_to_data rows (see
git history) — a real bug found via debug data where words sharing one
Tesseract "line" were getting joined with "\\n" instead of a space,
silently shredding the passport MRZ into fragments too short for
passport_ocr._extract_mrz_lines to recognize. That specific bug can't
recur under Vision: Vision's response already comes pre-structured into
pages/blocks/paragraphs/words (no flat list of same-line fragments to
misjoin), and response.full_text_annotation.text is Vision's own already-
reconstructed full text, not something this module rebuilds by hand. What
this module DOES still do by hand is flatten that nested structure into
OcrWord objects with a computed bounding box and a clamped confidence —
that's what these tests cover instead, using hand-built fake response
objects (see tests/vision_fakes.py) rather than a real Vision API call.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.ocr_client import _words_and_text_from_response
from tests.vision_fakes import empty_response, make_response


class WordsAndTextFromResponseTest(unittest.TestCase):
    def test_flattens_words_across_multiple_paragraphs(self):
        # Two paragraphs (as Vision would group the two physical MRZ
        # lines, for example) — both must contribute to the flat word
        # list, in reading order.
        response = make_response(
            full_text="P<LBNEL<ALAM<<GEORGES\nLR18962688LBN9109076M",
            word_specs=None,
            paragraphs=[
                [("P<LBNEL<ALAM<<GEORGES", 0.80, (0, 0, 220, 12))],
                [("LR18962688LBN9109076M", 0.88, (0, 20, 230, 32))],
            ],
        )
        words, full_text = _words_and_text_from_response(response)

        self.assertEqual(full_text, "P<LBNEL<ALAM<<GEORGES\nLR18962688LBN9109076M")
        self.assertEqual([w.text for w in words], ["P<LBNEL<ALAM<<GEORGES", "LR18962688LBN9109076M"])

    def test_full_text_passed_through_verbatim_not_rebuilt(self):
        # Unlike the old Tesseract path, this module trusts Vision's own
        # line reconstruction completely rather than rebuilding full_text
        # from the individual words — confirmed by using a full_text that
        # wouldn't match a naive "join the words with spaces" rebuild.
        response = make_response(
            full_text="line one\nline two, more spacing than the words below",
            word_specs=[("wordA", 0.9, (0, 0, 10, 10)), ("wordB", 0.9, (12, 0, 22, 10))],
        )
        _, full_text = _words_and_text_from_response(response)
        self.assertEqual(full_text, "line one\nline two, more spacing than the words below")

    def test_word_symbols_joined_without_separator(self):
        # A word's text is the concatenation of its symbols, not
        # space-joined -- Vision reports one symbol per character.
        response = make_response(full_text="O+", word_specs=[("O+", 0.75, (0, 0, 20, 15))])
        words, _ = _words_and_text_from_response(response)
        self.assertEqual(words[0].text, "O+")

    def test_bounding_box_is_min_max_of_vertices(self):
        response = make_response(full_text="X", word_specs=[("X", 0.9, (5, 8, 40, 33))])
        words, _ = _words_and_text_from_response(response)
        self.assertEqual(words[0].box, (5, 8, 40, 33))

    def test_confidence_passed_through_and_clamped_to_0_1(self):
        # Vision's word.confidence is already 0.0-1.0 (unlike Tesseract's
        # 0-100 scale this module used to rescale) -- still clamp
        # defensively rather than trust an out-of-range value verbatim.
        response = make_response(
            full_text="A B C",
            word_specs=[("A", 0.5, (0, 0, 5, 5)), ("B", 1.4, (6, 0, 11, 5)), ("C", -0.2, (12, 0, 17, 5))],
        )
        words, _ = _words_and_text_from_response(response)
        confidences = {w.text: w.confidence for w in words}
        self.assertEqual(confidences["A"], 0.5)
        self.assertEqual(confidences["B"], 1.0, "confidence above 1.0 must be clamped down")
        self.assertEqual(confidences["C"], 0.0, "confidence below 0.0 must be clamped up")

    def test_words_with_empty_symbol_text_are_skipped(self):
        response = make_response(full_text="A", word_specs=[("", 0.9, (0, 0, 1, 1)), ("A", 0.9, (2, 0, 7, 5))])
        words, _ = _words_and_text_from_response(response)
        self.assertEqual([w.text for w in words], ["A"])

    def test_no_full_text_annotation_returns_empty(self):
        words, full_text = _words_and_text_from_response(empty_response())
        self.assertEqual(words, [])
        self.assertEqual(full_text, "")


if __name__ == "__main__":
    unittest.main()
