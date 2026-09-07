"""
Lightweight stand-ins for the google.cloud.vision response shapes the OCR
tests need, built by hand rather than importing real
google.cloud.vision.types classes — those are protobuf-generated and
awkward to hand-construct in a test (many nested/oneof fields with no
simple public constructor). These plain Python dataclasses duck-type just
the attributes ocr_client._words_and_text_from_response actually reads:

    response.full_text_annotation.text
    response.full_text_annotation.pages[].blocks[].paragraphs[].words[]
    word.symbols[].text
    word.bounding_box.vertices[].x / .y
    word.confidence
    response.error.message

Not a test file itself (no TestCase subclasses, no test_ prefix), so
unittest's default discovery (test*.py) doesn't pick it up — import
directly from the tests that need it, the same way tests share fixtures
in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeVertex:
    x: int = 0
    y: int = 0


@dataclass
class FakeBoundingBox:
    vertices: list


@dataclass
class FakeSymbol:
    text: str


@dataclass
class FakeWord:
    symbols: list
    confidence: float
    bounding_box: FakeBoundingBox

    @classmethod
    def from_text(cls, text: str, confidence: float, box: tuple[int, int, int, int]) -> "FakeWord":
        x0, y0, x1, y1 = box
        return cls(
            symbols=[FakeSymbol(ch) for ch in text],
            confidence=confidence,
            bounding_box=FakeBoundingBox([
                FakeVertex(x0, y0), FakeVertex(x1, y0), FakeVertex(x1, y1), FakeVertex(x0, y1),
            ]),
        )


@dataclass
class FakeParagraph:
    words: list


@dataclass
class FakeBlock:
    paragraphs: list


@dataclass
class FakePage:
    blocks: list


@dataclass
class FakeFullTextAnnotation:
    text: str
    pages: list


@dataclass
class FakeError:
    message: str = ""


@dataclass
class FakeVisionResponse:
    full_text_annotation: object
    error: FakeError = field(default_factory=FakeError)


def make_response(full_text: str, word_specs, paragraphs: list | None = None) -> FakeVisionResponse:
    """Builds a FakeVisionResponse from a flat list of
    (text, confidence, (x0, y0, x1, y1)) tuples, all placed in a single
    page/block/paragraph unless `paragraphs` is given explicitly as a list
    of such word_specs lists (one per paragraph, for tests that care about
    paragraph grouping specifically)."""
    if paragraphs is None:
        paragraphs = [word_specs] if word_specs else []

    fake_paragraphs = [
        FakeParagraph(words=[FakeWord.from_text(t, c, b) for t, c, b in spec])
        for spec in paragraphs
    ]
    page = FakePage(blocks=[FakeBlock(paragraphs=fake_paragraphs)])
    annotation = FakeFullTextAnnotation(text=full_text, pages=[page] if full_text or word_specs else [])
    return FakeVisionResponse(full_text_annotation=annotation)


def empty_response() -> FakeVisionResponse:
    return FakeVisionResponse(full_text_annotation=FakeFullTextAnnotation(text="", pages=[]))
