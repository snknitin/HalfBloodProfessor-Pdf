"""Prompt and Structured Outputs contract for per-page annotations."""

PROMPT_VERSION = "b1-v1"

SYSTEM_PROMPT = """You are a sharp, current expert annotating one textbook page in ink.

Return only annotations grounded in the supplied page. Prefer specific corrections,
named results, dates, numbers, newer evidence, and better methods. The voice is terse,
confident, and slightly caustic: "Obviously dated — Göbekli Tepe, ~9500 BCE."

Safety and layout rules:
- Every quote must be a verbatim substring of the page containing 3-8 words.
- Never start or end a quote inside a hyphen-wrapped or line-split word.
- Emit at most 6 annotations for this page.
- Notes are at most 14 words. Corrections are at most 5 words.
- Use a diagram only when a short 2-5 node chain genuinely clarifies the page.
- Do not emit coordinates or page numbers. The deterministic renderer owns geometry.
- If nothing merits expert ink, return an empty annotations array.

Allowed annotation forms:
- underline: quote, optional note, and double
- strike: quote, correction, and optional note
- circle: quote and note
- highlight: quote
- scribble: quote and note
- doodle: quote and symbol (star, asterisk, or exclaim)
- margin: quote and note
- diagram: optional title and 2-5 labels
"""


def _object(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_QUOTE = {"type": "string", "minLength": 1}
_NOTE = {"type": "string", "minLength": 1}

ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "anyOf": [
                    _object(
                        {
                            "type": {"type": "string", "const": "underline"},
                            "quote": _QUOTE,
                            "note": {"anyOf": [_NOTE, {"type": "null"}]},
                            "double": {"type": "boolean"},
                        },
                        ["type", "quote", "note", "double"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "strike"},
                            "quote": _QUOTE,
                            "correction": {"type": "string", "minLength": 1},
                            "note": {"anyOf": [_NOTE, {"type": "null"}]},
                        },
                        ["type", "quote", "correction", "note"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "circle"},
                            "quote": _QUOTE,
                            "note": _NOTE,
                        },
                        ["type", "quote", "note"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "highlight"},
                            "quote": _QUOTE,
                        },
                        ["type", "quote"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "scribble"},
                            "quote": _QUOTE,
                            "note": _NOTE,
                        },
                        ["type", "quote", "note"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "doodle"},
                            "quote": _QUOTE,
                            "symbol": {
                                "type": "string",
                                "enum": ["star", "asterisk", "exclaim"],
                            },
                        },
                        ["type", "quote", "symbol"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "margin"},
                            "quote": _QUOTE,
                            "note": _NOTE,
                        },
                        ["type", "quote", "note"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "diagram"},
                            "title": {
                                "anyOf": [
                                    {"type": "string", "minLength": 1},
                                    {"type": "null"},
                                ]
                            },
                            "labels": {
                                "type": "array",
                                "minItems": 2,
                                "maxItems": 5,
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                        ["type", "title", "labels"],
                    ),
                ]
            },
        }
    },
    "required": ["annotations"],
    "additionalProperties": False,
}


RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "hb_page_annotations",
    "description": "Deterministic-renderer-safe annotations for one PDF page.",
    "strict": True,
    "schema": ANNOTATION_SCHEMA,
}
