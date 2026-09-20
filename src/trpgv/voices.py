import asyncio
import json
from pathlib import Path

import edge_tts

ZH = ("zh-CN", "zh-TW", "zh-HK")


async def _fetch() -> list[dict]:
    vs = await edge_tts.list_voices()
    return [
        {
            "id": v["ShortName"],
            "gender": v["Gender"],
            "locale": v["Locale"],
            "persona": v["VoiceTag"].get("VoicePersonalities", []),
            "category": [c.strip() for c in v["VoiceTag"].get("ContentCategories", [])],
        }
        for v in vs
        if v["Locale"].startswith(ZH)
    ]


def refresh(out: Path) -> list[dict]:
    vs = asyncio.run(_fetch())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(vs, ensure_ascii=False, indent=1), encoding="utf-8")
    return vs
