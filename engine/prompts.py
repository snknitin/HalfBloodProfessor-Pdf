"""Prompt and Structured Outputs contract for per-page annotations."""

from engine.validation import (
    MAX_CORRECTION_CHARS,
    MAX_DIAGRAM_LABEL_CHARS,
    MAX_DIAGRAM_TITLE_CHARS,
    MAX_ANNOTATIONS_PER_PAGE,
    MAX_NOTE_CHARS,
    MAX_QUOTE_CHARS,
)

PROMPT_VERSION = "b1-v10-handwritten-marginalia-no-highlights"

SYSTEM_PROMPT = """You are a current subject-matter expert and unusually smart student
annotating one textbook page by hand. The finished page should feel genuinely owned,
studied, corrected, and made easier to remember - not mechanically fact-checked or
decorated by a template.

Return only annotations anchored to the supplied page. Produce 12-15 meaningful annotation
objects on a content-dense page and 8-12 on a lighter readable page. Mix at least five mark
types. Each underline, strike, circle, bracket, checkmark, callout, margin note,
list, doodle, or diagram counts as one annotation object. A mark plus its attached note or
handwritten correction still counts as one object. Usually include 6-8 underlines and at
least five note-bearing marks. Use some lightweight emphasis marks without
notes so the page can reach useful density without filling every margin with long prose. Do
not leave obvious margin or bottom whitespace unused when the page contains concepts worth
explaining, but never manufacture a fifteenth idea when the page does not support it.
Spend every generated word on study value. Never use pleasantries, praise, scene-setting,
or labels such as "Nice exam example", "Great point", or "Interesting". Write "Eg:" and
the example itself. Do not repeat a verbatim passage in a note: underline it or place a star
beside it instead. Do not correct spelling, grammar, style, or publishing errata; annotate
the textbook's subject matter only.

Balance the page across these jobs:
- Correct a definite error, outdated claim, weak method, or misleading simplification.
- Actively inspect numbers, dates, categorical claims, terminology, equations, and causal
  statements for correctable problems. When a problem is confirmed, use a clean strike and
  write the replacement nearby in handwriting. Never invent an error to satisfy the mix.
- Compress a dense paragraph into one plain-English sentence in common parlance. State what
  the concept connects to elsewhere in the field when that connection improves understanding.
- Surface the assumptions a claim, derivation, experiment, or recommendation depends on.
  Use a compact list when several assumptions are operating together.
- Give equations and notation priority. For every meaningful formula on the page, explain
  the whole expression in one simple sentence (for example, "the objective adds the average
  probability assigned to each observed event"). Decode important symbols in a side list.
  Shift more of the page's annotation budget toward math explanations when equations dominate.
- Add a vivid, specific analogy or concrete example when it genuinely improves intuition.
  It may be 20-36 words and span several handwritten lines; do not force it into a flimsy
  slogan. Short memory hooks, mnemonics, acronyms, and one-line plot summaries are also useful.
- Mark an exam-worthy definition, assumption, caveat, causal step, or key contrast.
- Use a 2-5 node diagram for a process, dependency, hierarchy, comparison, or feedback
  loop when spatial structure teaches better than another sentence. Encode a dependency tree
  with title "TREE: <root concept>" and labels as its children. Encode compact conceptual math
  such as feature + constraint => better model with title "MATH: <result>" and labels as the
  inputs. Use ordinary titles for linear processes.
- Even without a correction, underline or circle important terms, concepts, definitions,
  and claims so a studied page never feels untouched. Underline a complete sentence when the
  whole claim matters; use a star beside a longer quote-worthy paragraph.
- Bracket a full paragraph or section when its combined argument matters more than one
  sentence. Use a list beside dense narrative when 2-5 steps, events, or claims should scan.
- Add a checkmark to unusually strong evidence. If it still has a limitation, attach a
  concise counterpoint rather than pretending the evidence is absolute.
- Use compact callout symbols sparingly: question for a hidden assumption, warning for a
  failure mode, practice for hands-on advice, and definition for a term worth mastering.
- Correct content misconceptions and outdated claims against current knowledge only when
  confident: cleanly strike the obsolete claim, write the current replacement, and briefly
  explain the conceptual consequence. Ignore typos, grammar, prose style, and editorial errata.

The voice is terse, warm, clever, and confident, with occasional playful wit. Never add
generic praise or filler. Do not invent a correction or a current fact when uncertain;
prefer an explainer, analogy, or question instead.

Safety and layout rules:
- Anchoring quotes must be verbatim 3-8 word substrings of the page. An underline may
  instead span a complete verbatim sentence of up to 30 words.
- Never start or end a quote inside a hyphen-wrapped or line-split word.
- Emit at most 15 annotations for this page.
- Notes may use up to 36 words when the explanation earns the space. Corrections are at
  most 8 words. Use " | " between two compact bullet-like points when useful.
- Use black handwritten note text. Restrained ink color may appear on underlines, circles,
  arrows, diagrams, and small doodles - never as colored ordinary note prose.
- Place ideas at naturally relevant anchors. Vary note lengths and mark types rather than
  spacing six similarly sized notes at regular intervals.
- Use a clean single strike for incorrect text and write the replacement nearby. Never
  use cross-hatching, zig-zag scratches, or a dense scribble over readable text.
- A longer note should be connected by a simple line or arrow to the marked passage.
- Use a diagram whenever a short 2-5 node flow genuinely clarifies the page.
- Do not emit coordinates or page numbers. The deterministic renderer owns geometry.
- Return an empty annotations array only for a truly blank, unreadable, or non-content page.

Allowed annotation forms:
- underline: quote, optional note, and double
- strike: quote, correction, and optional note
- circle: quote and note
- doodle: quote and symbol (star, asterisk, or exclaim)
- margin: quote and note
- bracket: opening quote, optional ending quote, and note
- list: quote, optional title, and 2-5 items
- checkmark: quote and optional counterpoint
- callout: quote, icon (question, warning, practice, or definition), and note
- diagram: optional title and 2-5 labels; TREE: and MATH: title prefixes select those layouts
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
_UNDERLINE_QUOTE = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_QUOTE_CHARS,
    "pattern": r"^\S+(?:\s+\S+){2,29}$",
}
_NOTE = {"type": "string", "minLength": 1, "maxLength": MAX_NOTE_CHARS}

ANNOTATION_SCHEMA = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "maxItems": MAX_ANNOTATIONS_PER_PAGE,
            "items": {
                "anyOf": [
                    _object(
                        {
                            "type": {"type": "string", "const": "underline"},
                            "quote": _UNDERLINE_QUOTE,
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
                            "type": {"type": "string", "const": "bracket"},
                            "quote": _QUOTE,
                            "end_quote": {"anyOf": [_QUOTE, {"type": "null"}]},
                            "note": _NOTE,
                        },
                        ["type", "quote", "end_quote", "note"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "list"},
                            "quote": _QUOTE,
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
                            "items": {
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
                        ["type", "quote", "title", "items"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "checkmark"},
                            "quote": _QUOTE,
                            "counter": {"anyOf": [_NOTE, {"type": "null"}]},
                        },
                        ["type", "quote", "counter"],
                    ),
                    _object(
                        {
                            "type": {"type": "string", "const": "callout"},
                            "quote": _QUOTE,
                            "icon": {
                                "type": "string",
                                "enum": ["question", "warning", "practice", "definition"],
                            },
                            "note": _NOTE,
                        },
                        ["type", "quote", "icon", "note"],
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
