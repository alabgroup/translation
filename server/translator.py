"""MT layer — kept behind one interface so vendors can be swapped/bake-off
tested per docs/SPEC.md §4 without touching the pipeline.

Two implementations to start:
  - ClaudeTranslator: the leading candidate — steerable via system prompt
    for sermon-specific handling (literal fragments, run-on cadence,
    theological register, glossary consistency).
  - DeepLTranslator: the fallback — best off-the-shelf quality among
    pure-NMT engines, least engineering effort, if Claude's latency or
    fragment-literalness doesn't hold up under real testing.
"""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod

LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "ko": "Korean",
    "zh": "Chinese",
    "vi": "Vietnamese",
    "tl": "Tagalog",
    "pt": "Portuguese",
    "fr": "French",
    "ja": "Japanese",
    "de": "German",
}


class Translator(ABC):
    @abstractmethod
    async def translate(
        self,
        text: str,
        context: list[str],
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str],
    ) -> str:
        ...


CLAUDE_SYSTEM_PROMPT = """You are a real-time interpreter for a live church \
service, translating spoken sermon audio from {source} to {target} as it is \
spoken, one short fragment at a time.

Rules — follow these exactly:
1. Translate ONLY the given fragment. Output nothing else: no notes, no \
quotation marks, no explanations.
2. The fragment may be a mid-sentence clause, not a complete sentence. \
Translate it AS a fragment. Never complete it, never summarize it, never \
add words that weren't spoken.
3. Preserve the speaker's run-on, conversational cadence. Do not "clean up" \
run-on sentences into shorter, tidier ones.
4. Match the register of spoken preaching/teaching — natural but reverent — \
not casual chat, not overly formal written prose.
5. Use this glossary consistently wherever a term appears: {glossary}
6. You will be given the last few already-translated fragments as context, \
purely so pronouns and continuations read coherently. Do not re-translate \
or repeat that context — translate only the new fragment."""


class ClaudeTranslator(Translator):
    def __init__(self, model: str = "claude-haiku-4-5-20251001", api_key: str | None = None):
        from anthropic import AsyncAnthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (see .env.example)")
        self._client = AsyncAnthropic(api_key=key)
        self._model = model

    async def translate(self, text, context, source_lang, target_lang, glossary):
        system = CLAUDE_SYSTEM_PROMPT.format(
            source=LANGUAGE_NAMES.get(source_lang, source_lang),
            target=LANGUAGE_NAMES.get(target_lang, target_lang),
            glossary=", ".join(f"{k} -> {v}" for k, v in glossary.items()) or "(none provided)",
        )
        context_block = "\n".join(context[-4:]) if context else "(none — this is the first fragment)"
        user_message = f"Prior translated context:\n{context_block}\n\nFragment to translate:\n{text}"

        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=300,
            temperature=0.2,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(block.text for block in resp.content if block.type == "text").strip()


def _deepl_target_code(lang: str) -> str:
    # DeepL requires region-qualified codes for a couple of targets.
    overrides = {"en": "EN-US", "pt": "PT-PT"}
    return overrides.get(lang, lang.upper())


class DeepLTranslator(Translator):
    def __init__(self, api_key: str | None = None):
        import deepl

        key = api_key or os.environ.get("DEEPL_API_KEY")
        if not key:
            raise RuntimeError("DEEPL_API_KEY is not set (see .env.example)")
        self._client = deepl.Translator(key)

    async def translate(self, text, context, source_lang, target_lang, glossary):
        # DeepL has no chat-style instructions — glossary consistency here
        # relies on its native glossary feature, not implemented in v1;
        # the client-supplied `glossary` dict is accepted for interface
        # parity but currently unused by this vendor. Flagged in SPEC §4.
        del glossary

        def _run() -> str:
            context_text = " ".join(context[-2:]) if context else None
            result = self._client.translate_text(
                text,
                source_lang=source_lang.upper(),
                target_lang=_deepl_target_code(target_lang),
                context=context_text,
            )
            return result.text

        return await asyncio.to_thread(_run)


def get_translator(vendor: str) -> Translator:
    if vendor == "claude":
        return ClaudeTranslator()
    if vendor == "deepl":
        return DeepLTranslator()
    raise ValueError(f"Unknown MT vendor: {vendor!r}")
