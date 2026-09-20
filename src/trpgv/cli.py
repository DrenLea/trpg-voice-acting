import argparse
import json
import os
from pathlib import Path

from . import characters, clean, llm, parse, script, voices


def main() -> None:
    ap = argparse.ArgumentParser(prog="trpgv")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="原始 log → lines.jsonl")
    p.add_argument("log", type=Path)
    p.add_argument("-w", "--work", type=Path, required=True)

    c = sub.add_parser("clean", help="规则清洗 → clean.jsonl")
    c.add_argument("-w", "--work", type=Path, required=True)
    c.add_argument("--llm", action="store_true", help="规则层之后再跑 LLM 判定层")

    ch = sub.add_parser("chars", help="clean.jsonl → characters.json")
    ch.add_argument("-w", "--work", type=Path, required=True)
    ch.add_argument("--voices", type=Path, default=Path("assets/voices.json"))

    s = sub.add_parser("script", help="clean.jsonl + characters.json → scenes/*.md + script.md")
    s.add_argument("-w", "--work", type=Path, required=True)
    s.add_argument("--scene", type=int, help="只重生成第 N 幕")
    s.add_argument("--smart", action="store_true", help="用 sonnet 生成剧本（默认 haiku）")

    a = sub.add_parser("audio", help="script.md → TTS + 混音 → out/*.mp3")
    a.add_argument("-w", "--work", type=Path, required=True)

    v = sub.add_parser("voices", help="拉取 edge-tts 中文声线 → assets/voices.json（--azure 拉 Azure 全量 → voices_azure.json）")
    v.add_argument("-o", "--out", type=Path, default=Path("assets/voices.json"))
    v.add_argument("--azure", action="store_true")

    al = sub.add_parser("all", help="parse → clean --llm → chars → script → audio")
    al.add_argument("log", type=Path)
    al.add_argument("-w", "--work", type=Path, required=True)

    wb = sub.add_parser("web", help="启动 Web 工作台")
    wb.add_argument("--port", type=int, default=8765)
    wb.add_argument("--host", default="127.0.0.1")

    af = sub.add_parser("assets", help="按 out/missing_assets.txt 从 Openverse 自动下载音效/BGM")
    af.add_argument("-w", "--work", type=Path, required=True)

    ts = sub.add_parser("tts-server", help="启动本地 Qwen3-TTS 服务（描述造声线 + 克隆），需 GPU 与 pip install trpgv[qwen]")
    ts.add_argument("--port", type=int, default=8880)
    ts.add_argument("--base", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base", help="克隆模型（显存紧张可用 0.6B-Base）")
    ts.add_argument("--design", default="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    ts.add_argument("--dir", type=Path, default=Path("assets/voices_qwen"), help="设计声线存放目录")
    ts.add_argument("--device", default="cuda")
    ts.add_argument("--keep-design", action="store_true", help="造声线后不卸载设计模型（需 ≥12GB 显存）")

    args = ap.parse_args()

    if args.cmd == "tts-server":
        from . import ttsserver

        os.chdir(Path(__file__).resolve().parents[2])
        print(f"http://127.0.0.1:{args.port}/v1  ← 填到工作台设置 tts_base_url，tts_engine=openai")
        ttsserver.serve(args.port, args.base, args.design, args.dir, args.device, args.keep_design)
        return

    if args.cmd == "assets":
        from . import assets as ov

        f = args.work / "out" / "missing_assets.txt"
        items = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
        for r in ov.auto_fill(items):
            print(("OK  " if r["ok"] else "MISS") + f" {r['kind']} {r['desc']} ← {r.get('title', r['q'])}")
        return

    if args.cmd == "web":
        from . import web

        os.chdir(Path(__file__).resolve().parents[2])
        print(f"http://{args.host}:{args.port}")
        web.serve(args.host, args.port)
        return

    if args.cmd == "all":
        import sys

        w = str(args.work)
        for step in (["parse", str(args.log), "-w", w], ["clean", "-w", w, "--llm"], ["chars", "-w", w],
                     ["script", "-w", w], ["audio", "-w", w]):
            print(f"== {step[0]}")
            sys.argv = ["trpgv", *step]
            main()
        return

    if args.cmd == "voices":
        if args.azure:
            from .tts import engine_from

            e = engine_from({"tts_engine": "azure"})
            vs = voices.refresh_azure(args.out if args.out != Path("assets/voices.json") else Path("assets/voices_azure.json"),
                                      e["region"], e["key"])
        else:
            vs = voices.refresh(args.out)
        for x in vs:
            extra = f" styles={len(x['styles'])} roles={len(x['roles'])}" if "styles" in x else ""
            print(f"{x['id']:34} {x['gender']:6} {'/'.join(x['persona'])}{extra}")
        return

    args.work.mkdir(parents=True, exist_ok=True)

    if args.cmd == "parse":
        lines = parse.parse(args.log)
        parse.dump(lines, args.work / "lines.jsonl")
        print(f"parsed {len(lines)} lines -> {args.work / 'lines.jsonl'}")
    elif args.cmd == "clean":
        lines = parse.load(args.work / "lines.jsonl")
        out, stats = clean.clean_rules(lines)
        if args.llm:
            out, audit = clean.clean_llm(out)
            (args.work / "drops.jsonl").write_text(
                "\n".join(json.dumps(a, ensure_ascii=False) for a in audit), encoding="utf-8"
            )
            stats["llm_drop"] = len(audit)
            stats["kept"] = len(out)
        parse.dump(out, args.work / "clean.jsonl")
        (args.work / "clean.txt").write_text(
            "\n".join(f"【{l.role}】{l.text}" for l in out), encoding="utf-8"
        )
        print(json.dumps(stats, ensure_ascii=False))
    elif args.cmd == "chars":
        lines = parse.load(args.work / "clean.jsonl")
        data = characters.build(lines, args.voices)
        out = args.work / "characters.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(data['roles'])} roles + narrator -> {out}")
    elif args.cmd == "script":
        out = script.build(args.work, model=llm.SMART if args.smart else llm.CHEAP, only=args.scene)
        print(f"-> {out}")
    elif args.cmd == "audio":
        from . import config, mix, tts

        cfg = config.load(args.work)
        chars = tts.load_chars(args.work)
        events = tts.synth(args.work / "script.md", chars, cfg["tts_concurrency"],
                           tts.engine_from(cfg), config.load_lines(args.work))
        mix.mix(events, args.work / "out", cfg, config.load_cues(args.work))


if __name__ == "__main__":
    main()
