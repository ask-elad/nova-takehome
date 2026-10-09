"""Judge: a single yes/no question with a ref.

Used by rules at report time for atomic cross-document judgement calls
(e.g. "does the DG fee apply when the declaration says refrigerant only?").
Fast tier, cached by (question, context, doc, pages).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel

from nova.case import SourceRef
from nova.llm import LLMClient
from nova.readers import UNTRUSTED_SYSTEM
from nova.schemas import Ref

prompt_version = "judge-1"


class JudgeAnswer(BaseModel):
    answer: bool
    ref: Ref


class Judge:
    """Call Claude with a yes/no question about a specific document."""

    def __init__(self, client: LLMClient):
        self._client = client

    def ask(
        self,
        question_id: str,
        question: str,
        doc_id: str,
        pages: list[str],
        extra_context: Optional[Mapping[str, Any]] = None,
    ) -> tuple[bool, Optional[SourceRef]]:
        from nova.mailbox import render_pages
        from nova.schemas import flatten_schema

        rendered = render_pages(pages)
        ctx = ""
        if extra_context:
            ctx = "\nContext:\n" + "\n".join(f"- {k}: {v}" for k, v in extra_context.items()) + "\n"
        user = (
            f"Question ({question_id}): {question}\n"
            f"Answer true or false, and cite the single line of the document that\n"
            f"supports your answer.{ctx}\n"
            f"<document doc=\"{doc_id}\">\n{rendered}\n</document>\n"
        )
        schema = flatten_schema(JudgeAnswer.model_json_schema())
        raw = self._client.call(
            tier="fast", purpose="judge",
            messages=[{"role": "user", "content": user}],
            schema=schema, prompt_version=prompt_version,
            system=UNTRUSTED_SYSTEM, max_tokens=256,
        )
        try:
            ans = JudgeAnswer.model_validate(raw)
        except Exception:
            return False, None
        return ans.answer, SourceRef.from_ref(doc_id, ans.ref)
