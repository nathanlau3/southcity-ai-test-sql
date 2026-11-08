"""Factory model LLM via LangChain.

Model default (gpt-6-luna) adalah reasoning model, jadi `temperature` tidak dikirim.
`reasoning_effort` diatur lewat LLM_REASONING_EFFORT; kosongkan untuk model
non-reasoning. Structured output memakai json_schema (strict).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from text2sql.config import get_settings

T = TypeVar("T", bound=BaseModel)


@lru_cache
def get_llm() -> BaseChatModel:
    s = get_settings()
    kwargs: dict = {"max_tokens": 16000}
    if s.openai_api_key:
        kwargs["api_key"] = s.openai_api_key
    if s.llm_reasoning_effort:
        kwargs["reasoning_effort"] = s.llm_reasoning_effort
    return init_chat_model(s.llm_model, **kwargs)


def structured_llm(schema: type[T]) -> Runnable:
    return get_llm().with_structured_output(schema, method="json_schema")
