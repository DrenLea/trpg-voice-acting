import json
import re
from collections import defaultdict
from pathlib import Path

from . import llm
from .parse import Line

SAMPLE_PER_ROLE = 12
KP_ROLES = {"KP", "kp", "DM", "dm", "GM", "gm", "守密人", "主持人"}


def build(lines: list[Line], voices_path: Path) -> dict:
    by_role: dict[str, list[str]] = defaultdict(list)
    player_of: dict[str, str] = {}
    for ln in lines:
        if ln.text.startswith("[骰子") or len(by_role[ln.role]) >= SAMPLE_PER_ROLE:
            continue
        by_role[ln.role].append(ln.text[:160])
        player_of.setdefault(ln.role, ln.player)

    voices = json.loads(voices_path.read_text(encoding="utf-8"))
    pool = "\n".join(f"{v['id']} {v['gender']} {'/'.join(v['persona'])}" for v in voices if v["locale"] == "zh-CN")
    roles_txt = "\n\n".join(
        f"## {r}（{'KP' if r in KP_ROLES else 'PC'}，昵称 {player_of[r]}）\n" + "\n".join(f"- {s}" for s in ss)
        for r, ss in by_role.items()
    )
    raw = llm.ask(llm.prompt("characters"), f"# 声线池\n{pool}\n\n# 角色样本\n{roles_txt}", max_tokens=3000)
    m = re.search(r"\{.*\}", raw, re.S)
    return json.loads(m[0] if m else raw)
