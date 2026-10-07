"""Chat model factory: primary OpenAI-compatible endpoint (DeepSeek), with OpenRouter as fallback."""
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from . import config


class MissingModelConfig(RuntimeError):
    pass


def _chat(model_id: str, base_url: str, api_key: str, title: bool = False) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_id,
        base_url=base_url,
        api_key=api_key,
        temperature=0.7,
        timeout=float(config.get("MODEL_TIMEOUT_S", "180")),
        max_retries=1,
        default_headers={"X-Title": "PersonaLab"} if title else None,
    )


def chat_model() -> BaseChatModel:
    api_key = config.get("MODEL_API_KEY")
    base_url = config.get("MODEL_BASE_URL", "https://api.deepseek.com/v1")
    model_id = config.get("MODEL_ID")
    missing = [name for name, value in (("MODEL_API_KEY", api_key), ("MODEL_ID", model_id)) if not value]
    if missing:
        raise MissingModelConfig(f"Missing model settings: {', '.join(missing)} (set them in .env.local / .env)")
    primary = _chat(model_id, base_url, api_key, title="openrouter.ai" in base_url)
    fallback_key = config.get("OPENROUTER_API_KEY")
    if not fallback_key or "openrouter.ai" in base_url:
        return primary
    fallback = _chat(config.get("FALLBACK_MODEL_ID", "deepseek/deepseek-v4.1-flash"), "https://openrouter.ai/api/v1", fallback_key, title=True)
    return primary.with_fallbacks([fallback])
