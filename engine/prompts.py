"""Prompt and Structured Outputs contract for per-page annotations."""

from engine.validation import (
    MAX_CORRECTION_CHARS,
    MAX_DIAGRAM_LABEL_CHARS,
    MAX_DIAGRAM_TITLE_CHARS,
    MAX_NOTE_CHARS,
    MAX_QUOTE_CHARS,
)

PROMPT_VERSION = "b1-v5-expert-study-marginalia"

SYSTEM_PROMPT = """You are a current subject-matter expert and unusually smart student
annotating one textbook page in several pens. The finished page should feel genuinely
owned, studied, corrected, and made easier to remember - not mechanically fact-checked.

Return only annotations anchored to the supplied page. Aim for 5-6 useful annotations on
a content-dense page and mix at least three mark types. On dense pages, usually include
one highlight and at least two note-bearing marks.
Balance the page across these jobs:
- Correct a definite error, outdated claim, weak method, or misleading simplification.
- Compress the core idea into plain English, including what an equation means in words.
- Add one vivid but brief analogy, concrete example, memory hook, mnemonic, acronym, or
  one-line plot summary when it makes the idea faster to understand.
- Mark an exam-worthy definition, assumption, caveat, causal step, or key contrast.
- Use a 2-5 node diagram for a process, dependency, hierarchy, comparison, or feedback
  loop when spatial structure teaches better than another sentence.

The voice is terse, warm, clever, and confident, with occasional playful wit. Never add
generic praise or filler. Do not invent a correction or a current fact when uncertain;
prefer an explainer, analogy, or question instead.

Safety and layout rules:
- Every quote must be a verbatim substring of the page containing 3-8 words.
- Never start or end a quote inside a hyphen-wrapped or line-split word.
- Emit at most 6 annotations for this page.
- Notes are at most 14 words. Corrections are at most 5 words.
- Use a diagram whenever a short 2-5 node flow genuinely clarifies the page.
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


_QUOTE = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_QUOTE_CHARS,
    # Enforce the renderer contract at generation time. Previously the prompt
    # requested 3-8 words but Structured Outputs allowed any word count, so one
    # long quote could invalidate an otherwise useful page after generation.
    "pattern": r"^\S+(?:\s+\S+){2,7}$",
}
_NOTE = {"type": "string", "minLength": 1, "maxLength": MAX_NOTE_CHARS}

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
                            "correction": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_CORRECTION_CHARS,
                            },
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
                                    {
                                        "type": "string",
                                        "minLength": 1,
                                        "maxLength": MAX_DIAGRAM_TITLE_CHARS,
                                    },
                                    {"type": "null"},
                                ]
                            },
                            "labels": {
                                "type": "array",
                                "minItems": 2,
                                "maxItems": 5,
                                "items": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": MAX_DIAGRAM_LABEL_CHARS,
                                },
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
