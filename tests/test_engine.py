"""Engine reliability tests. These never make a live OpenAI request."""

import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz
from fastapi import HTTPException
from starlette.requests import Request

from engine import main
from engine import render
from engine.prompts import ANNOTATION_SCHEMA
from engine.validation import (
    MAX_CORRECTION_CHARS,
    MAX_DIAGRAM_LABEL_CHARS,
    MAX_DIAGRAM_TITLE_CHARS,
    MAX_NOTE_CHARS,
    MAX_QUOTE_CHARS,
)


def make_pdf(page_texts):
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 760), text, fontsize=10)
    result = doc.tobytes()
    doc.close()
    return result


def page_text(marker="normal"):
    return " ".join(
        [
            f"Alpha beta gamma describes the {marker} central relationship and its modern use."
            for _ in range(35)
        ]
    )


class FakeResponses:
    def __init__(self):
        self.calls = 0
        self.handler = self._default

    async def create(self, **kwargs):
        self.calls += 1
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_output_tokens"] == 700
        assert kwargs["text"]["format"]["strict"] is True
        return self.handler(kwargs)

    @staticmethod
    def _default(_kwargs):
        payload = {
            "annotations": [
                {
                    "type": "underline",
                    "quote": "Alpha beta gamma",
                    "note": "Core relationship; keep this.",
                    "double": False,
                }
            ]
        }
        return SimpleNamespace(output_text=json.dumps(payload))


def parse_sse(value):
    events = []
    for frame in value.split("\n\n"):
        if not frame.strip():
            continue
        event = next(
            (line.removeprefix("event: ") for line in frame.splitlines() if line.startswith("event: ")),
            None,
        )
        raw = next(
            (line.removeprefix("data: ") for line in frame.splitlines() if line.startswith("data: ")),
            None,
        )
        if raw:
            events.append((event, json.loads(raw)))
    return events


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._memory_cache.clear()
        main._cache_locks.clear()
        self.fake_responses = FakeResponses()
        main._client = SimpleNamespace(responses=self.fake_responses)
        self.old_retry_rng = main._retry_rng
        main._retry_rng = SimpleNamespace(uniform=lambda _a, _b: 0.001)
        self.env = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "placeholder-not-used",
                "HB_MODEL": "test-model",
                "HB_SHARED_SECRET": "test-secret",
                "HB_DOCUMENT_DEADLINE_SECONDS": "10",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        main._client = None
        main._retry_rng = self.old_retry_rng

    async def test_processes_unique_pages_concurrently_caches_and_is_deterministic(self):
        pdf = make_pdf([page_text("one"), page_text("two"), "Short cover page"])
        progress = []

        async def record_progress(event):
            progress.append(event)

        first = await main._process_pdf(pdf, record_progress)
        second = await main._process_pdf(pdf)

        self.assertEqual(self.fake_responses.calls, 2)
        self.assertEqual(first.pdf_bytes, second.pdf_bytes)
        self.assertEqual(first.metadata["skipped_pages"], [3])
        self.assertIn("thinking 3/3", [event["stage"] for event in progress])
        self.assertEqual(progress[-1]["stage"], "scribbling")

        rendered = fitz.open(stream=first.pdf_bytes, filetype="pdf")
        self.assertEqual(rendered.page_count, 3)
        self.assertGreaterEqual(len(rendered[0].get_drawings()), 1)
        self.assertGreaterEqual(len(rendered[1].get_drawings()), 1)
        rendered.close()

    async def test_valid_empty_is_distinct_and_cacheable(self):
        self.fake_responses.handler = lambda _kwargs: SimpleNamespace(
            output_text='{"annotations":[]}'
        )
        deadline = asyncio.get_running_loop().time() + 5
        first = await main._annotations_for_page(page_text("empty"), deadline, 1)
        second = await main._annotations_for_page(page_text("empty"), deadline, 1)
        self.assertEqual(first.status, "valid_empty")
        self.assertEqual(second.status, "valid_empty")
        self.assertTrue(second.cache_hit)
        self.assertEqual(self.fake_responses.calls, 1)

    async def test_operational_failure_is_classified_and_never_cached(self):
        def fail(_kwargs):
            raise RuntimeError("secret upstream detail must not be retained")

        self.fake_responses.handler = fail
        deadline = asyncio.get_running_loop().time() + 5
        with self.assertLogs(main.logger, level="WARNING") as captured:
            first = await main._annotations_for_page(page_text("failure"), deadline, 1)
            second = await main._annotations_for_page(page_text("failure"), deadline, 1)
        self.assertEqual(first.status, "failed")
        self.assertEqual(first.error_category, "operational_error")
        self.assertEqual(second.status, "failed")
        self.assertEqual(self.fake_responses.calls, 2)
        self.assertEqual(main._memory_cache, {})
        self.assertNotIn("secret upstream detail", "\n".join(captured.output))

    async def test_malformed_nonempty_response_is_not_valid_empty_or_cached(self):
        self.fake_responses.handler = lambda _kwargs: SimpleNamespace(
            output_text=json.dumps(
                {"annotations": [{"type": "highlight", "quote": "too short"}]}
            )
        )
        deadline = asyncio.get_running_loop().time() + 5
        result = await main._annotations_for_page(page_text("malformed"), deadline, 1)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_category, "parse_error")
        self.assertEqual(self.fake_responses.calls, 2)
        self.assertEqual(main._memory_cache, {})

    async def test_retry_stops_when_document_deadline_has_no_budget(self):
        def timeout(_kwargs):
            raise asyncio.TimeoutError("do not expose this")

        self.fake_responses.handler = timeout
        deadline = asyncio.get_running_loop().time() + 0.1
        result = await main._annotations_for_page(page_text("timeout"), deadline, 1)
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(result.error_category, "document_deadline")
        self.assertEqual(self.fake_responses.calls, 1)

    async def test_too_many_failed_pages_fail_the_document_with_metadata(self):
        self.fake_responses.handler = lambda _kwargs: (_ for _ in ()).throw(
            RuntimeError("upstream failed")
        )
        pdf = make_pdf([page_text("fail-one"), page_text("fail-two")])
        with self.assertRaises(main.DocumentProcessingError) as raised:
            await main._process_pdf(pdf)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("2 of 2 readable pages", raised.exception.detail)
        self.assertEqual(len(raised.exception.metadata["failed_pages"]), 2)

    async def test_partial_failure_appears_in_sse_progress_and_done_metadata(self):
        def selective(kwargs):
            if "FAILPAGE" in kwargs["input"]:
                raise RuntimeError("upstream failed")
            return FakeResponses._default(kwargs)

        self.fake_responses.handler = selective
        pdf = make_pdf(
            [page_text("ok-one"), page_text("ok-two"), page_text("FAILPAGE"),
             page_text("ok-four"), page_text("ok-five")]
        )
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": pdf, "more_body": False}

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/annotate",
                "query_string": b"stream=1",
                "headers": [(b"content-type", b"application/pdf")],
            },
            receive,
        )
        response = await main.annotate(request, stream=True, x_hb_auth="test-secret")
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        events = parse_sse("".join(chunks))

        failure_progress = [
            data for event, data in events
            if event == "progress" and data.get("status") == "failed"
        ]
        self.assertEqual(len(failure_progress), 1)
        self.assertEqual(failure_progress[0]["page"], 3)
        self.assertEqual(failure_progress[0]["error_category"], "operational_error")
        done = next(data for event, data in events if event == "done")
        self.assertEqual(done["metadata"]["failed_pages"][0]["page"], 3)
        self.assertTrue(done["pdf_base64"])

    async def test_rejects_scanned_or_empty_pdf(self):
        with self.assertRaises(HTTPException) as raised:
            await asyncio.to_thread(main._extract_pages, make_pdf([""]))
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("digital-text", raised.exception.detail)

    async def test_rejects_more_than_50_pages(self):
        with self.assertRaises(HTTPException) as raised:
            await asyncio.to_thread(main._extract_pages, make_pdf(["text"] * 51))
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("50 pages", raised.exception.detail)

    async def test_auth_uses_required_shared_secret(self):
        main._verify_auth("test-secret")
        with self.assertRaises(HTTPException) as raised:
            main._verify_auth("wrong")
        self.assertEqual(raised.exception.status_code, 401)

    async def test_sse_payload_is_named_and_json_encoded(self):
        event = main._sse("progress", {"stage": "scribbling"})
        self.assertEqual(event, 'event: progress\ndata: {"stage":"scribbling"}\n\n')


class RendererReliabilityTests(unittest.TestCase):
    def test_one_bad_annotation_cannot_fail_the_document(self):
        pdf = make_pdf([page_text()])
        annotations = [
            {"page": 1, "type": "circle", "quote": "Alpha beta gamma", "note": "bad"},
            {"page": 1, "type": "underline", "quote": "Alpha beta gamma", "double": False},
        ]
        with self.assertLogs(render.logger, level="WARNING") as captured:
            with patch("engine.render.scribe.circle", side_effect=RuntimeError("bad geometry")):
                rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertEqual(report.metadata()["error_count"], 1)
        self.assertNotIn("bad geometry", "\n".join(captured.output))
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        self.assertEqual(rendered.page_count, 1)
        self.assertGreaterEqual(len(rendered[0].get_drawings()), 1)
        rendered.close()

    def test_page_setup_failure_is_isolated_from_other_pages(self):
        pdf = make_pdf([page_text("page-one"), page_text("page-two")])
        annotations = [
            {"page": 1, "type": "underline", "quote": "Alpha beta gamma", "double": False},
            {"page": 2, "type": "underline", "quote": "Alpha beta gamma", "double": False},
        ]
        original_margins = render.Margins

        def fail_first_page(page):
            if page.number == 0:
                raise RuntimeError("bad page geometry")
            return original_margins(page)

        with patch("engine.render.Margins", side_effect=fail_first_page):
            rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertEqual(report.errors[0]["type"], "page")
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        self.assertEqual(len(rendered[0].get_drawings()), 0)
        self.assertGreaterEqual(len(rendered[1].get_drawings()), 1)
        rendered.close()

    def test_extreme_quote_rectangle_is_clamped_to_page(self):
        pdf = make_pdf([page_text()])
        annotations = [
            {"page": 1, "type": "highlight", "quote": "Alpha beta gamma"},
        ]
        with patch("engine.render.find_quote", return_value=[fitz.Rect(-100, -100, 1000, 1000)]):
            rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertEqual(report.errors, [])
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        bounds = rendered[0].rect
        for drawing in rendered[0].get_drawings():
            rect = drawing["rect"]
            self.assertGreaterEqual(rect.x0, bounds.x0)
            self.assertGreaterEqual(rect.y0, bounds.y0)
            self.assertLessEqual(rect.x1, bounds.x1)
            self.assertLessEqual(rect.y1, bounds.y1)
        rendered.close()

    def test_correction_box_stays_inside_page_at_edge_anchor(self):
        pdf = make_pdf([page_text()])
        annotations = [
            {
                "page": 1,
                "type": "strike",
                "quote": "Alpha beta gamma",
                "correction": "bounded correction text",
            },
        ]
        edge = fitz.Rect(560, 4, 594, 16)
        with patch("engine.render.find_quote", return_value=[edge]):
            rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertEqual(report.errors, [])
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        bounds = rendered[0].rect
        for block in rendered[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    rect = fitz.Rect(span["bbox"])
                    self.assertGreaterEqual(rect.x0, bounds.x0)
                    self.assertGreaterEqual(rect.y0, bounds.y0)
                    self.assertLessEqual(rect.x1, bounds.x1)
                    self.assertLessEqual(rect.y1, bounds.y1)
        rendered.close()

    def test_malformed_diagram_is_isolated_without_losing_other_ink(self):
        pdf = make_pdf([page_text()])
        annotations = [
            {"page": 1, "type": "underline", "quote": "Alpha beta gamma", "double": False},
            {
                "page": 1,
                "type": "diagram",
                "title": "A bounded diagram",
                "labels": ["valid label", {"not": "text"}],
            },
        ]
        rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertTrue(
            any(item["type"] == "diagram" for item in report.errors),
            report.errors,
        )
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        self.assertGreaterEqual(len(rendered[0].get_drawings()), 1)
        rendered.close()

    @unittest.skipUnless(
        os.path.exists(os.path.join(ROOT, "samples", "Ch1 - Introductions.pdf")),
        "local Ch1 acceptance fixture is not present",
    )
    def test_ch1_acceptance_fixture_renders(self):
        with open(os.path.join(ROOT, "app", "annotations_ch1.json"), encoding="utf-8") as source:
            annotations = json.load(source)
        with open(os.path.join(ROOT, "samples", "Ch1 - Introductions.pdf"), "rb") as source:
            pdf = source.read()
        rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertGreater(len(rendered_bytes), 0)
        self.assertEqual(report.errors, [])
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        self.assertEqual(rendered.page_count, 42)
        rendered.close()


class PromptContractTests(unittest.TestCase):
    def test_schema_caps_annotations_fields_and_disallows_extra_fields(self):
        annotations = ANNOTATION_SCHEMA["properties"]["annotations"]
        self.assertEqual(annotations["maxItems"], 6)
        self.assertFalse(ANNOTATION_SCHEMA["additionalProperties"])
        variants = annotations["items"]["anyOf"]
        self.assertEqual(variants[0]["properties"]["quote"]["maxLength"], MAX_QUOTE_CHARS)
        self.assertEqual(variants[0]["properties"]["note"]["anyOf"][0]["maxLength"], MAX_NOTE_CHARS)
        self.assertEqual(variants[1]["properties"]["correction"]["maxLength"], MAX_CORRECTION_CHARS)
        diagram = variants[-1]["properties"]
        self.assertEqual(diagram["title"]["anyOf"][0]["maxLength"], MAX_DIAGRAM_TITLE_CHARS)
        self.assertEqual(diagram["labels"]["items"]["maxLength"], MAX_DIAGRAM_LABEL_CHARS)

    def test_sanitizer_enforces_character_caps_before_rendering_or_cache(self):
        payload = {
            "annotations": [
                {
                    "type": "strike",
                    "quote": "one two three " + "q" * 500,
                    "correction": "c" * 500,
                    "note": "n" * 500,
                },
                {
                    "type": "diagram",
                    "title": "t" * 500,
                    "labels": ["a" * 500, "b" * 500],
                },
            ]
        }
        clean = main._sanitize_annotations(payload)
        self.assertLessEqual(len(clean[0]["quote"]), MAX_QUOTE_CHARS)
        self.assertLessEqual(len(clean[0]["correction"]), MAX_CORRECTION_CHARS)
        self.assertLessEqual(len(clean[0]["note"]), MAX_NOTE_CHARS)
        self.assertLessEqual(len(clean[1]["title"]), MAX_DIAGRAM_TITLE_CHARS)
        self.assertTrue(all(len(label) <= MAX_DIAGRAM_LABEL_CHARS for label in clean[1]["labels"]))


if __name__ == "__main__":
    unittest.main()
