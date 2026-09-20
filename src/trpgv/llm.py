import os
from pathlib import Path

import anthropic

CHEAP = "claude-haiku-4-5"
SMART = "claude-sonnet-5"
_client: anthropic.Anthropic | None = None


def _load_env() -> None:
    # 项目 .env 优先于 shell 环境变量，避免外部残留的 key 覆盖
    for p in (Path(".env"), Path(__file__).resolve().parents[2] / ".env"):
        if p.exists():
            break
    else:
        return
    for s in p.read_text(encoding="utf-8").splitlines():
        if "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            if v.strip():
                os.environ[k.strip()] = v.strip()


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _load_env()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("未配置 ANTHROPIC_API_KEY：复制 .env.example 为 .env 并填入密钥（如走中转站再填 ANTHROPIC_BASE_URL）")
        _client = anthropic.Anthropic()
    return _client


def ask(system: str, user: str, model: str = CHEAP, max_tokens: int = 2048, prefill: str = "") -> str:
    msgs = [{"role": "user", "content": user}]
    if prefill:
        msgs.append({"role": "assistant", "content": prefill})
    r = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=msgs,
    )
    return prefill + "".join(b.text for b in r.content if b.type == "text").strip()


def prompt(name: str) -> str:
    return Path(__file__).resolve().parents[2].joinpath("prompts", f"{name}.md").read_text(encoding="utf-8")
