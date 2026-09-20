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


def refresh_azure(out: Path, region: str, key: str) -> list[dict]:
    """Azure Speech 全量中文声线（含 style / role 能力），写入 assets/voices_azure.json。"""
    import urllib.request

    from .tts import azure_base

    req = urllib.request.Request(f"{azure_base(region)}/cognitiveservices/voices/list",
                                 headers={"Ocp-Apim-Subscription-Key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = json.loads(r.read())
    vs = [
        {
            "id": v["ShortName"],
            "gender": v["Gender"],
            "locale": v["Locale"],
            "name": v.get("LocalName", ""),
            "persona": v.get("VoiceTag", {}).get("VoicePersonalities", []),
            "category": [c.strip() for c in v.get("VoiceTag", {}).get("ContentCategories", [])],
            "styles": v.get("StyleList", []),
            "roles": v.get("RolePlayList", []),
        }
        for v in raw
        if v["Locale"].startswith(ZH) and v.get("Status") != "Deprecated"
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(vs, ensure_ascii=False, indent=1), encoding="utf-8")
    return vs
