import re

from .parse import Line

BOT_ROLES = {"骰子", "骰娘", "Dice", "dice"}
OOC_OPEN = ("(", "（", "//", "场外")
RESULT = re.compile(r"D100=\d+/\d+\s*(?P<res>(?:大|困难|极难)?(?:成功|失败))")
SKILL_ROLL = re.compile(r"^<\[[^\]]+\](?P<role>[^>]*)>\s*(?P<skill>[^:：]*)[:：]\s*(?P<body>.+)$", re.S)
PLAIN_ROLL = re.compile(r"^\s*(?P<expr>\d*d\d+(?:[+\-]\d+)?)\s*=\s*(?P<val>\d+)", re.I)


def _fold_dice(text: str) -> tuple[str, str] | None:
    """Return (roller_role, folded_text) for a bot line worth keeping, else None."""
    m = SKILL_ROLL.match(text.strip())
    if not m:
        return None
    body = m["body"]
    if r := RESULT.search(body):
        skill = m["skill"].strip()
        return m["role"].strip(), f"[骰子: {skill} {r['res']}]"
    if p := PLAIN_ROLL.match(body):
        return m["role"].strip(), f"[骰子: {p['expr']}={p['val']}]"
    return None


def _strip_ooc(text: str) -> str:
    kept = [s for s in text.split("\n") if s.strip() and not s.lstrip().startswith(OOC_OPEN)]
    return "\n".join(kept)


def clean_rules(lines: list[Line]) -> tuple[list[Line], dict[str, int]]:
    stats = {"total": len(lines), "bot_drop": 0, "cmd": 0, "ooc": 0, "dice_kept": 0, "merged": 0}
    out: list[Line] = []
    for ln in lines:
        if ln.role in BOT_ROLES or "暗骰" in ln.text and ln.text.startswith("来自"):
            folded = _fold_dice(ln.text)
            if not folded:
                stats["bot_drop"] += 1
                continue
            role, text = folded
            stats["dice_kept"] += 1
            out.append(Line(ln.i, "", role, text))
            continue
        if ln.text.startswith("."):
            stats["cmd"] += 1
            continue
        text = _strip_ooc(ln.text)
        if not text:
            stats["ooc"] += 1
            continue
        if out and out[-1].role == ln.role and out[-1].player == ln.player and not text.startswith("[骰子"):
            out[-1].text += "\n" + text
            stats["merged"] += 1
            continue
        out.append(Line(ln.i, ln.player, ln.role, text))
    stats["kept"] = len(out)
    return out, stats


CHUNK = 120
DROP_LINE = re.compile(r"^\s*(\d+)\s+(rule|chat|meta|dup)\b")


def clean_llm(lines: list[Line]) -> tuple[list[Line], list[dict]]:
    from . import llm

    system = llm.prompt("clean")
    drops: dict[int, str] = {}
    for start in range(0, len(lines), CHUNK):
        chunk = lines[start : start + CHUNK]
        user = "\n".join(f"{ln.i}|{ln.role}|{ln.text.replace(chr(10), ' / ')}" for ln in chunk)
        for m in DROP_LINE.finditer(llm.ask(system, user)):
            drops[int(m[1])] = m[2]
    kept = [ln for ln in lines if ln.i not in drops]
    audit = [{"i": ln.i, "why": drops[ln.i], "role": ln.role, "text": ln.text} for ln in lines if ln.i in drops]
    return kept, audit
