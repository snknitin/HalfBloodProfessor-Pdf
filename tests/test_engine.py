"""B1 service tests. These never make a live OpenAI request."""

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

from engine import main
from engine.prompts import ANNOTATION_SCHEMA


def make_pdf(page_texts):
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 760), text, fontsize=10)
    result = doc.tobytes()
    doc.close()
    return result


class FakeResponses:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_output_tokens"] == 700
        assert kwargs["text"]["format"]["strict"] is True
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


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._memory_cache.clear()
        main._cache_locks.clear()
        self.fake_responses = FakeResponses()
        main._client = SimpleNamespace(responses=self.fake_responses)
        self.env = patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "placeholder-not-used",
                "HB_MODEL": "test-model",
                "HB_SHARED_SECRET": "test-secret",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        main._client = None

    async def test_processes_concurrently_caches_and_renders_deterministically(self):
        text = " ".join(
            [
                "Alpha beta gamma describes the central relationship and its modern use."
                for _ in range(35)
            ]
        )
        pdf = make_pdf([text, text, "Short cover page"])
        progress = []

        async def record_progress(stage):
            progress.append(stage)

        first = await main._process_pdf(pdf, record_progress)
        second = await main._process_pdf(pdf)

        self.assertEqual(self.fake_responses.calls, 1)
        self.assertEqual(first, second)
        self.assertIn("thinking 3/3", progress)
        self.assertEqual(progress[-1], "scribbling")

        rendered = fitz.open(stream=first, filetype="pdf")
        self.assertEqual(rendered.page_count, 3)
        self.assertGreaterEqual(len(rendered[0].get_drawings()), 1)
        self.assertGreaterEqual(len(rendered[1].get_drawings()), 1)
        rendered.close()

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
        self.assertEqual(
            event,
            'event: progress\ndata: {"stage":"scribbling"}\n\n',
        )


class PromptContractTests(unittest.TestCase):
    def test_schema_caps_annotations_and_disallows_extra_fields(self):
        annotations = ANNOTATION_SCHEMA["properties"]["annotations"]
        self.assertEqual(annotations["maxItems"], 6)
        self.assertFalse(ANNOTATION_SCHEMA["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
