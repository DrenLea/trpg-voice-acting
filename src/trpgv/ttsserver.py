"""Qwen3-TTS 本地服务：文字描述造声线（VoiceDesign）+ 固定声线克隆（Base），暴露 OpenAI 兼容 /v1/audio/speech。

工作台把 tts_engine 设为 openai、tts_base_url 指向本服务即可。需要 `pip install trpgv[qwen]` 与 NVIDIA 显卡。
"""
import hashlib
import io
import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

BASE = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
DESIGN = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
PREFIX = "design:"

app = FastAPI(title="trpgv qwen3-tts")
opts = {"base": BASE, "design": DESIGN, "dir": Path("assets/voices_qwen"), "device": "cuda", "keep_design": False}
models: dict[str, object] = {}
prompts: dict[str, object] = {}
lock = threading.Lock()


def _load(kind: str):
    if kind not in models:
        import torch
        from qwen_tts import Qwen3TTSModel

        print(f"loading {opts[kind]} ...", flush=True)
        models[kind] = Qwen3TTSModel.from_pretrained(opts[kind], device_map=opts["device"], dtype=torch.bfloat16)
    return models[kind]


def _unload(kind: str) -> None:
    if models.pop(kind, None) is not None:
        import gc

        import torch

        gc.collect()
        torch.cuda.empty_cache()


def _mp3(wav, sr: int) -> bytes:
    import imageio_ffmpeg
    import numpy as np
    from pydub import AudioSegment

    AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    pcm = (np.clip(wav, -1, 1) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    AudioSegment(data=pcm, sample_width=2, frame_rate=sr, channels=1).export(buf, format="mp3", bitrate="64k")
    return buf.getvalue()


def _profiles() -> list[dict]:
    out = []
    for m in sorted(opts["dir"].glob("*/meta.json")):
        out.append(json.loads(m.read_text(encoding="utf-8")))
    return out


def _prompt(vid: str):
    if vid not in prompts:
        d = opts["dir"] / vid
        if not (d / "meta.json").exists():
            raise HTTPException(404, f"未知声线 {vid}")
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        with lock:
            prompts[vid] = _load("base").create_voice_clone_prompt(ref_audio=str(d / "reference.wav"),
                                                                   ref_text=meta["text"], x_vector_only_mode=False)
    return prompts[vid]


@app.get("/health")
def health():
    return {"ok": True, "loaded": list(models), "voices": len(_profiles())}


@app.get("/v1/voices")
def voices():
    return {"voices": [{"id": PREFIX + p["id"], "name": p["name"], "desc": p["instruct"]} for p in _profiles()],
            "design": True}


class Speech(BaseModel):
    input: str
    voice: str
    model: str = "tts-1"
    speed: float = 1.0
    instructions: str = ""
    response_format: str = "mp3"


@app.post("/v1/audio/speech")
def speech(b: Speech):
    if not b.voice.startswith(PREFIX):
        raise HTTPException(400, f"本服务只支持设计声线（{PREFIX}xxx），先在角色表「造声线」")
    vid = b.voice[len(PREFIX):]
    pr = _prompt(vid)
    with lock:
        wavs, sr = _load("base").generate_voice_clone(text=b.input, language="Chinese", voice_clone_prompt=pr)
    return Response(_mp3(wavs[0], sr), media_type="audio/mpeg")


class Design(BaseModel):
    name: str
    instruct: str
    text: str = "你好，我是这个角色，这是我的声线试听。"


@app.post("/v1/voice-design")
def design(b: Design):
    """按描述生成参考音并存为可复用声线；返回试听 mp3，响应头 X-Voice-Id。"""
    vid = re.sub(r"[^A-Za-z0-9_-]", "", b.name)[:32] or "v_" + hashlib.sha1(b.name.encode()).hexdigest()[:8]
    d = opts["dir"] / vid
    d.mkdir(parents=True, exist_ok=True)
    with lock:
        wavs, sr = _load("design").generate_voice_design(text=b.text, language="Chinese", instruct=b.instruct)
        if not opts["keep_design"]:
            _unload("design")
    import soundfile as sf

    sf.write(str(d / "reference.wav"), wavs[0], sr)
    (d / "meta.json").write_text(json.dumps({"id": vid, "name": b.name, "instruct": b.instruct, "text": b.text},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
    prompts.pop(vid, None)
    return Response(_mp3(wavs[0], sr), media_type="audio/mpeg", headers={"X-Voice-Id": PREFIX + vid})


@app.delete("/v1/voices/{vid}")
def delete(vid: str):
    import shutil

    vid = vid.removeprefix(PREFIX)
    shutil.rmtree(opts["dir"] / vid, ignore_errors=True)
    prompts.pop(vid, None)
    return {"ok": True}


def serve(port: int, base: str, design_model: str, out: Path, device: str, keep_design: bool) -> None:
    import uvicorn

    opts.update({"base": base, "design": design_model, "dir": out, "device": device, "keep_design": keep_design})
    out.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=port)
