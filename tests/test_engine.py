"""Engine reliability tests. These never make a live OpenAI request."""

import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz
from fastapi import HTTPException
from starlette.requests import Request

from engine import main
from engine import render
from engine import books
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
        assert kwargs["max_output_tokens"] == 3_200
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
        return SimpleNamespace(
            output_text=json.dumps(payload),
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=30,
                input_tokens_details=SimpleNamespace(cached_tokens=20),
                output_tokens_details=SimpleNamespace(reasoning_tokens=0),
            ),
        )


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
        self.assertEqual(first.metadata["usage"]["input_tokens"], 240)
        self.assertEqual(first.metadata["usage"]["cached_input_tokens"], 40)
        self.assertEqual(first.metadata["retries"], 0)
        self.assertEqual(first.metadata["render"]["quote_match_percent"], 100.0)
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

    async def test_tier_file_limits_match_the_published_offer(self):
        self.assertEqual(main._tier_limits("free"), (20 * 1024 * 1024, 50))
        self.assertEqual(main._tier_limits("teacher"), (50 * 1024 * 1024, 150))

    async def test_diagrams_are_distributed_across_eight_page_windows(self):
        self.fake_responses.handler = lambda _kwargs: SimpleNamespace(
            output_text=json.dumps(
                {
                    "annotations": [
                        {
                            "type": "diagram",
                            "title": "Fast map",
                            "labels": ["input", "process", "result"],
                        }
                    ]
                }
            )
        )
        pdf = make_pdf([page_text(f"diagram-{index}") for index in range(9)])
        empty_report = render.RenderReport()
        with patch(
            "engine.main.annotate_bytes", return_value=(pdf, empty_report)
        ) as renderer:
            await main._process_pdf(pdf)
        rendered_annotations = renderer.call_args.args[1]
        diagrams = [item for item in rendered_annotations if item["type"] == "diagram"]
        self.assertEqual([item["page"] for item in diagrams], [1, 9])

    async def test_auth_uses_required_shared_secret(self):
        main._verify_auth("test-secret")
        with self.assertRaises(HTTPException) as raised:
            main._verify_auth("wrong")
        self.assertEqual(raised.exception.status_code, 401)

    async def test_sse_payload_is_named_and_json_encoded(self):
        event = main._sse("progress", {"stage": "scribbling"})
        self.assertEqual(event, 'event: progress\ndata: {"stage":"scribbling"}\n\n')


class RendererReliabilityTests(unittest.TestCase):
    def test_wrapped_vertical_diagram_labels_stay_inside_separate_nodes(self):
        doc = fitz.open()
        page = doc.new_page()
        area = fitz.Rect(20, 40, 145, 430)
        labels = [
            "cheap retrieval adds candidates",
            "reranker scores candidates",
            "top results fit context better",
            "reranking pipeline",
        ]
        shape = page.new_shape()
        import random

        with patch.object(
            render.scribe, "node_text", wraps=render.scribe.node_text
        ) as node_text:
            render.scribe.chain_diagram(
                page, shape, area, labels, random.Random(11), title="RAG stages"
            )
        node_boxes = [fitz.Rect(call.args[1]) for call in node_text.call_args_list]
        self.assertEqual(len(node_boxes), len(labels))
        for index, box in enumerate(node_boxes):
            self.assertGreaterEqual(box.x0, area.x0)
            self.assertLessEqual(box.x1, area.x1)
            if index:
                self.assertGreaterEqual(box.y0, node_boxes[index - 1].y1 + 14)
        doc.close()

    def test_long_notes_prefer_safe_horizontal_page_margins(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 25), "Chapter heading", fontsize=9)
        page.insert_textbox(
            fitz.Rect(72, 100, 540, 650),
            "Dense textbook content explains the system and its practical behavior. " * 20,
            fontsize=10,
        )
        page.insert_text((290, 820), "12", fontsize=8)
        margins = render.Margins(page)
        note = (
            "Practical rule: retrieve broadly, rerank precisely, then reserve context "
            "space for the evidence that can change the answer."
        )
        box, side = margins.place(380, note)
        self.assertIn(side, {"top", "bottom"})
        self.assertGreater(box.width, max(margins.left.width, margins.right.width))
        self.assertLessEqual(box.y1, getattr(margins, side).y1)
        doc.close()

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

    def test_marks_use_multiple_deterministic_ink_colors(self):
        pdf = make_pdf([page_text()])
        annotations = [
            {"page": 1, "type": "strike", "quote": "Alpha beta gamma", "correction": "Better term"},
            {"page": 1, "type": "underline", "quote": "central relationship and its", "double": True},
            {"page": 1, "type": "highlight", "quote": "current evidence, measured results,"},
        ]
        first, first_report = render.annotate_bytes(pdf, annotations)
        second, second_report = render.annotate_bytes(pdf, annotations)
        self.assertEqual(first, second)
        self.assertEqual(first_report.errors, second_report.errors)
        rendered = fitz.open(stream=first, filetype="pdf")
        colors = {
            tuple(round(value, 3) for value in drawing["color"])
            for drawing in rendered[0].get_drawings()
            if drawing.get("color") is not None
        }
        self.assertGreaterEqual(len(colors), 2)
        rendered.close()

    def test_highlight_meanings_map_to_stable_colors(self):
        expected = {
            "key": render.scribe.HIGHLIGHT,
            "theory": render.scribe.HIGHLIGHT_ORANGE,
            "definition": render.scribe.HIGHLIGHT_BLUE,
            "evidence": render.scribe.HIGHLIGHT_GREEN,
            "caution": render.scribe.HIGHLIGHT_RED,
        }
        for meaning, color in expected.items():
            self.assertEqual(
                render._annotation_color(
                    {"type": "highlight", "meaning": meaning}, None
                ),
                color,
            )

    def test_bracket_list_checkmark_and_callout_render_safely(self):
        text = " ".join(
            [
                "Opening argument explains the mechanism in detail.",
                "Dense narrative presents several steps for the learner.",
                "Strong evidence supports this result in practice.",
                "Practical limitation appears during deployment at scale.",
                "Ending claim completes the mechanism with a clear conclusion.",
            ]
            * 8
        )
        pdf = make_pdf([text])
        annotations = [
            {
                "page": 1,
                "type": "bracket",
                "quote": "Opening argument explains the mechanism",
                "end_quote": "Ending claim completes the mechanism",
                "note": "This span forms one complete argument.",
            },
            {
                "page": 1,
                "type": "list",
                "quote": "Dense narrative presents several steps",
                "title": "Working sequence",
                "items": ["Observe the input", "Apply the rule", "Check the result"],
            },
            {
                "page": 1,
                "type": "checkmark",
                "quote": "Strong evidence supports this result",
                "counter": "Strong evidence, but verify the deployment population.",
            },
            {
                "page": 1,
                "type": "callout",
                "quote": "Practical limitation appears during deployment",
                "icon": "warning",
                "note": "Field failure mode: monitor this boundary first.",
            },
        ]
        rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.annotations_received, 4)
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        self.assertGreater(len(rendered[0].get_drawings()), 4)
        rendered.close()

    def test_annotation_prose_and_corrections_render_in_black_ink(self):
        pdf = make_pdf([page_text()])
        annotations = [
            {
                "page": 1,
                "type": "underline",
                "quote": "central relationship and its",
                "note": "A longer expert explanation belongs in readable black handwriting.",
                "double": False,
            },
            {
                "page": 1,
                "type": "strike",
                "quote": "Alpha beta gamma",
                "correction": "Use the current term",
            },
        ]
        with patch("engine.render.scribe.note_text", wraps=render.scribe.note_text) as notes:
            rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertGreater(len(rendered_bytes), 0)
        self.assertEqual(report.errors, [])
        self.assertTrue(notes.call_args_list)
        self.assertTrue(
            all(call.kwargs.get("color") == render.scribe.INK for call in notes.call_args_list)
        )

    def test_genuinely_blank_interior_page_gets_zero_token_doodle(self):
        pdf = make_pdf([page_text("opening"), "", page_text("closing")])
        rendered_bytes, report = render.annotate_bytes(pdf, [])
        self.assertEqual(report.blank_page_doodles, 1)
        rendered = fitz.open(stream=rendered_bytes, filetype="pdf")
        self.assertGreater(len(rendered[1].get_drawings()), 0)
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


class BookPipelineTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"HB_SHARED_SECRET": "test-secret", "HB_BOOK_RESULT_DIR": os.path.join(ROOT, ".test-book-results")},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        result_dir = os.path.join(ROOT, ".test-book-results")
        if os.path.isdir(result_dir):
            for filename in os.listdir(result_dir):
                os.unlink(os.path.join(result_dir, filename))
            os.rmdir(result_dir)
        self.env.stop()

    def test_toc_chunks_follow_chapters_and_split_long_chapter(self):
        toc = [[1, "Chapter One", 1], [1, "Chapter Two", 61], [2, "A detail", 70]]
        chunks = books._plan_chunks(120, toc)
        self.assertEqual(chunks[0].source, "toc")
        self.assertEqual((chunks[0].start_page, chunks[0].end_page), (1, 50))
        self.assertIn("Chapter One", chunks[0].title)
        self.assertEqual(chunks[-1].end_page, 120)

    def test_no_toc_falls_back_to_numbered_fifty_page_parts(self):
        chunks = books._plan_chunks(120, [])
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].title, "Part 1 of 3 (pages 1-50)")
        self.assertEqual((chunks[-1].start_page, chunks[-1].end_page), (101, 120))

    def test_encrypted_result_requires_same_key_and_round_trips(self):
        pdf = make_pdf([page_text("encrypted")])
        result_id, _ = books.save_encrypted_result(pdf, "hb-aaaa-bbbb-cccc-dddd")
        self.assertEqual(books.latest_result("hb-aaaa-bbbb-cccc-dddd")["result_id"], result_id)
        self.assertEqual(books.load_encrypted_result(result_id, "hb-aaaa-bbbb-cccc-dddd"), pdf)
        with self.assertRaises(HTTPException) as raised:
            books.load_encrypted_result(result_id, "hb-zzzz-yyyy-xxxx-wwww")
        self.assertEqual(raised.exception.status_code, 403)

    def test_encrypted_result_is_deleted_after_24_hours(self):
        pdf = make_pdf([page_text("expiry")])
        now = int(books.time.time())
        with patch("engine.books.time.time", return_value=now):
            result_id, _ = books.save_encrypted_result(pdf, "hb-aaaa-bbbb-cccc-dddd")
        with patch("engine.books.time.time", return_value=now + books.RESULT_TTL_SECONDS + 1):
            with self.assertRaises(HTTPException) as raised:
                books.load_encrypted_result(result_id, "hb-aaaa-bbbb-cccc-dddd")
        self.assertEqual(raised.exception.status_code, 410)

    def test_1200_pages_get_friendly_split_message(self):
        pdf = make_pdf(["short"] * 1200)
        with self.assertRaises(HTTPException) as raised:
            books.inspect_book(pdf)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("split it into two passes", raised.exception.detail)


class BookCreditTests(unittest.IsolatedAsyncioTestCase):
    async def test_book_authorization_is_reserved_before_stream_processing(self):
        async def request_with_body():
            sent = False

            async def receive():
                nonlocal sent
                if sent:
                    return {"type": "http.disconnect"}
                sent = True
                return {"type": "http.request", "body": b"pdf", "more_body": False}

            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/annotate-book",
                    "headers": [],
                },
                receive,
            )

        access_key = "hb-aaaa-bbbb-cccc-dddd"
        main._redeemed_book_tokens.clear()
        main._active_book_keys.clear()
        try:
            with (
                patch("engine.main.latest_result", side_effect=HTTPException(404)),
                patch("engine.main._verify_book_token", return_value="first-token-long-enough"),
            ):
                response = await main.annotate_book(
                    await request_with_body(), access_key, "signed-token"
                )
            self.assertEqual(response.media_type, "text/event-stream")
            self.assertIn("first-token-long-enough", main._redeemed_book_tokens)
            self.assertIn(access_key, main._active_book_keys)

            with patch("engine.main._verify_book_token", return_value="first-token-long-enough"):
                with self.assertRaises(HTTPException) as replayed:
                    await main.annotate_book(
                        await request_with_body(), access_key, "signed-token"
                    )
            self.assertEqual(replayed.exception.status_code, 409)

            with patch("engine.main._verify_book_token", return_value="second-token-long-enough"):
                with self.assertRaises(HTTPException) as duplicate_key:
                    await main.annotate_book(
                        await request_with_body(), access_key, "another-signed-token"
                    )
            self.assertEqual(duplicate_key.exception.status_code, 409)
            self.assertIn("already has a book", duplicate_key.exception.detail)
        finally:
            main._redeemed_book_tokens.clear()
            main._active_book_keys.clear()

    async def test_failed_book_never_calls_success_credit_callback(self):
        plan = books.BookChunk(1, "Chapter One", 1, 1, "toc")
        progress = AsyncMock()
        with (
            patch("engine.main.inspect_book", return_value=(1, [plan])),
            patch("engine.main.extract_chunk", return_value=b"chunk"),
            patch("engine.main._process_pdf", AsyncMock(side_effect=RuntimeError("forced failure"))),
            patch("engine.main._notify_book_success", AsyncMock()) as callback,
        ):
            with self.assertRaises(RuntimeError):
                await main._process_book(b"source", "hb-aaaa-bbbb-cccc-dddd", "token-id-long-enough", progress)
        callback.assert_not_awaited()

    async def test_success_callback_receives_exact_result_expiry(self):
        plan = books.BookChunk(1, "Chapter One", 1, 1, "toc")
        processed = main.ProcessResult(b"annotated", {"usage": {}})
        progress = AsyncMock()
        with (
            patch("engine.main.inspect_book", return_value=(1, [plan])),
            patch("engine.main.extract_chunk", return_value=b"chunk"),
            patch("engine.main._process_pdf", AsyncMock(return_value=processed)),
            patch("engine.main.original_toc", return_value=[]),
            patch("engine.main.stitch_chunks", return_value=b"stitched"),
            patch(
                "engine.main.save_encrypted_result",
                return_value=("result-id-long-enough", 1234567890),
            ),
            patch(
                "engine.main._notify_book_success", AsyncMock(return_value=True)
            ) as callback,
        ):
            result = await main._process_book(
                b"source",
                "hb-aaaa-bbbb-cccc-dddd",
                "token-id-long-enough",
                progress,
            )
        callback.assert_awaited_once_with(
            "hb-aaaa-bbbb-cccc-dddd", "result-id-long-enough", 1234567890
        )
        self.assertTrue(result.metadata["credit_consumed"])


class PromptContractTests(unittest.TestCase):
    def test_schema_caps_annotations_fields_and_disallows_extra_fields(self):
        annotations = ANNOTATION_SCHEMA["properties"]["annotations"]
        self.assertEqual(annotations["maxItems"], 15)
        self.assertFalse(ANNOTATION_SCHEMA["additionalProperties"])
        variants = annotations["items"]["anyOf"]
        self.assertEqual(variants[0]["properties"]["quote"]["maxLength"], MAX_QUOTE_CHARS)
        self.assertEqual(
            variants[0]["properties"]["quote"]["pattern"],
            r"^\S+(?:\s+\S+){2,29}$",
        )
        self.assertEqual(
            variants[1]["properties"]["quote"]["pattern"],
            r"^\S+(?:\s+\S+){2,7}$",
        )
        self.assertEqual(variants[0]["properties"]["note"]["anyOf"][0]["maxLength"], MAX_NOTE_CHARS)
        self.assertEqual(variants[1]["properties"]["correction"]["maxLength"], MAX_CORRECTION_CHARS)
        diagram = variants[-1]["properties"]
        self.assertEqual(diagram["title"]["anyOf"][0]["maxLength"], MAX_DIAGRAM_TITLE_CHARS)
        self.assertEqual(diagram["labels"]["items"]["maxLength"], MAX_DIAGRAM_LABEL_CHARS)

    def test_prompt_requests_expert_study_value_without_more_page_calls(self):
        self.assertIn("plain-English", main.SYSTEM_PROMPT)
        self.assertIn("mnemonic", main.SYSTEM_PROMPT)
        self.assertIn("20-36 words", main.SYSTEM_PROMPT)
        self.assertIn("12-15 meaningful annotation", main.SYSTEM_PROMPT)
        self.assertIn("6-8 underlines", main.SYSTEM_PROMPT)
        self.assertIn("Never invent an error", main.SYSTEM_PROMPT)
        self.assertIn("black handwritten note text", main.SYSTEM_PROMPT)
        self.assertIn("zig-zag scratches", main.SYSTEM_PROMPT)
        self.assertIn("Never use pleasantries", main.SYSTEM_PROMPT)
        self.assertIn('Write "Eg:"', main.SYSTEM_PROMPT)
        self.assertIn("TREE:", main.SYSTEM_PROMPT)
        self.assertIn("MATH:", main.SYSTEM_PROMPT)
        self.assertIn("Surface the assumptions", main.SYSTEM_PROMPT)
        self.assertIn("Do not correct spelling, grammar", main.SYSTEM_PROMPT)
        self.assertNotIn("highlight:", main.SYSTEM_PROMPT)

    def test_tree_and_math_diagrams_render_without_errors(self):
        pdf = make_pdf(["A concept depends on feature choice and a practical constraint. " * 20])
        annotations = [
            {
                "page": 1,
                "type": "diagram",
                "title": "TREE: model quality",
                "labels": ["data", "objective", "evaluation"],
            },
            {
                "page": 1,
                "type": "diagram",
                "title": "MATH: robust model",
                "labels": ["good features", "constraints"],
            },
        ]
        rendered_bytes, report = render.annotate_bytes(pdf, annotations)
        self.assertTrue(rendered_bytes.startswith(b"%PDF"))
        self.assertEqual(report.errors, [])

    def test_sanitizer_allows_sentence_underlines(self):
        long_quote = "one two three four five six seven eight nine ten eleven twelve"
        payload = {
            "annotations": [
                {"type": "underline", "quote": long_quote, "double": False},
            ]
        }
        clean = main._sanitize_annotations(payload)
        self.assertEqual([item["type"] for item in clean], ["underline"])

    def test_prompt_schema_no_longer_generates_scribbles(self):
        variants = ANNOTATION_SCHEMA["properties"]["annotations"]["items"]["anyOf"]
        generated_types = {
            variant["properties"]["type"]["const"] for variant in variants
        }
        self.assertNotIn("scribble", generated_types)
        self.assertNotIn("highlight", generated_types)
        self.assertTrue({"bracket", "list", "checkmark", "callout"} <= generated_types)

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

    def test_sanitizer_preserves_longer_multiline_expert_notes(self):
        note = " ".join(f"word{index}" for index in range(30))
        payload = {
            "annotations": [
                {
                    "type": "margin",
                    "quote": "three useful exact words",
                    "note": note,
                }
            ]
        }
        clean = main._sanitize_annotations(payload)
        self.assertEqual(clean[0]["note"], note)
        self.assertEqual(len(clean[0]["note"].split()), 30)

    def test_sanitizer_isolates_invalid_items_and_defaults_optional_fields(self):
        payload = {
            "annotations": [
                {"type": "highlight", "quote": "too short"},
                {
                    "type": "underline",
                    "quote": "three useful exact words",
                    "note": "Worth remembering.",
                },
                {"type": "margin", "quote": "another exact useful phrase", "note": "Sharper framing."},
            ]
        }
        clean = main._sanitize_annotations(payload)
        self.assertEqual([item["type"] for item in clean], ["underline", "margin"])
        self.assertFalse(clean[0]["double"])

    def test_sanitizer_rejects_a_wholly_invalid_nonempty_page(self):
        with self.assertRaises(ValueError):
            main._sanitize_annotations(
                {"annotations": [{"type": "highlight", "quote": "too short"}]}
            )

    def test_sanitizer_accepts_fifteen_annotations_and_rejects_sixteen(self):
        annotation = {
            "type": "underline",
            "quote": "three useful exact words",
            "double": False,
        }
        fifteen = {"annotations": [dict(annotation) for _ in range(15)]}
        self.assertEqual(len(main._sanitize_annotations(fifteen)), 15)
        with self.assertRaisesRegex(ValueError, "Too many annotations"):
            main._sanitize_annotations(
                {"annotations": [dict(annotation) for _ in range(16)]}
            )


if __name__ == "__main__":
    unittest.main()
