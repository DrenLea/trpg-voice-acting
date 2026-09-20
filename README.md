# trpg-voice-acting

[中文](#中文) · [English](#english)

---

## 中文

把跑团（TRPG）文字记录变成多角色广播剧：**清洗 → 拆角色配声线 → 逐幕改写剧本 → 音效/BGM → TTS 混音出片**。

### 特点

- **省 token**：解析、正则清洗、合并、缓存全用代码；LLM 只做判定与改写，按块/按幕处理，默认 `claude-haiku-4-5`（实测比 sonnet 更守剧本格式）。
- **不改剧情**：提示词硬规则——不增删情节、不改人设、不添加原文没有的心理活动；三类格式校验 + 带错误反馈自动重试。
- **免费声线库，引擎可换**：默认 edge-tts 14 个中文神经声线，可试听选择；设置页一键切到任何 OpenAI 兼容 `/v1/audio/speech` 本地服务（Kokoro-FastAPI、CosyVoice、Index-TTS 等），角色语气自动作为风格指令传入。不做真人声线克隆。
- **台词级微调**：剧本页可对单句覆盖声线 / 语速 / 音调 / 风格，留空即用角色默认，只重合成改动的句子。
- **免费素材库**：Openverse API（Freesound 音效 + Jamendo 音乐，CC 授权，无需密钥）按剧本描述自动检索下载，自动记录署名。
- **可监修**：剧本是 Markdown（`【角色】台词` / `[音效]` / `「BGM: …」`），改一幕只重跑一幕；TTS 按行缓存，只重合成改动的台词。
- **Web 工作台**：导入、运行、选声线试听、改剧本、找素材、逐段替换/静音/调音量 BGM 与音效、混音参数设置、试听成片，一页搞定。

### 安装

需要 Python ≥ 3.11（推荐 3.13）和 [uv](https://github.com/astral-sh/uv)。无需系统 ffmpeg。

```bash
git clone https://github.com/DrenLea/trpg-voice-acting.git
cd trpg-voice-acting
uv venv && uv pip install -e .
cp .env.example .env   # 填入 ANTHROPIC_API_KEY
```

### 使用

```bash
trpgv web                                  # 启动工作台 http://127.0.0.1:8765（推荐）

# 或命令行
trpgv voices                               # 拉取 edge-tts 中文声线 → assets/voices.json
trpgv all samples/xxx.txt -w work/xxx      # parse → clean → chars → script → audio
trpgv script -w work/xxx --scene 3         # 监修后只重跑第 3 幕
trpgv assets -w work/xxx                   # 按缺失清单从 Openverse 自动下载音效/BGM
trpgv audio  -w work/xxx                   # 重新合成混音（未改动的台词走缓存）
```

支持 `.txt` / `.docx`，记录格式为 `<[昵称]角色>:内容`（骰娘昵称含"骰子"）。其他格式改 `src/trpgv/parse.py` 里的一条正则即可。

### 流程与产物

| 步骤 | 输入 → 输出 | 说明 |
|---|---|---|
| parse | log → `lines.jsonl` | 纯代码 |
| clean | → `clean.jsonl` / `drops.jsonl` | 规则层删指令/骰娘文案/场外行，折叠骰点；LLM 层只输出「序号 原因码」 |
| chars | → `characters.json` | KP 拆为旁白 + NPC，每角色性格/语气/voice |
| script | → `scenes/NN.md` + `script.md` | 逐幕改写；新 NPC `【？名】` 自动登记 |
| audio | → `out/NN_标题.mp3` + `full.mp3` | edge-tts + pydub 混音，BGM -18 dB 淡入淡出 |

### 目录

```
src/trpgv/      parse / clean / characters / script / tts / mix / assets / web / cli
prompts/        LLM 固定前缀（命中提示缓存）
assets/         voices.json · tags.json（关键词→文件）· sfx/ bgm/（不入库，自动下载）· ATTRIBUTION.txt
docs/           01-需求与设计 · 02-开发方案（含实测结论）
work/<项目>/    运行产物（不入库）
```

### 素材授权

`trpgv assets` 下载的文件为 CC0 / CC BY / CC BY-NC 等，署名信息写在 `assets/ATTRIBUTION.txt`。发布成片前请核对各条授权（BY 需署名，NC 不可商用，ND 不可改编）。

---

## English

Turn text-based TRPG session logs into a multi-voice audio drama: **clean → split roles & assign voices → rewrite scene by scene → SFX/BGM → TTS mix**.

### Highlights

- **Token-frugal**: parsing, regex cleaning, merging and caching are plain code; the LLM only judges and rewrites, chunk-by-chunk / scene-by-scene, defaulting to `claude-haiku-4-5` (empirically more format-compliant than sonnet for this task).
- **Plot-faithful**: hard prompt rules — no added or removed plot, no personality drift, no invented inner monologue; three format validators with error-fed automatic retry.
- **Free voices, swappable engine**: 14 Chinese neural voices from edge-tts by default, previewable in the UI; switch in Settings to any OpenAI-compatible `/v1/audio/speech` local server (Kokoro-FastAPI, CosyVoice, Index-TTS…) — each character's tone is passed as the style instruction. No voice cloning.
- **Per-line tuning**: override voice / rate / pitch / style for a single line from the script page; blank fields fall back to the character; only changed lines are re-synthesized.
- **Free asset library**: Openverse API (Freesound SFX + Jamendo music, CC-licensed, no API key) searched automatically from script cues, with attribution recorded.
- **Reviewable**: the script is Markdown (`【Role】line` / `[sfx]` / `「BGM: …」`); edit one scene, rerun one scene; TTS is cached per line.
- **Web workbench**: import, run steps, pick & preview voices, edit scenes, find assets, replace / mute / re-level every BGM and SFX cue, tune mix parameters, listen to the result — one page.

### Install

Python ≥ 3.11 (3.13 recommended) and [uv](https://github.com/astral-sh/uv). No system ffmpeg needed.

```bash
git clone https://github.com/DrenLea/trpg-voice-acting.git
cd trpg-voice-acting
uv venv && uv pip install -e .
cp .env.example .env   # set ANTHROPIC_API_KEY
```

### Usage

```bash
trpgv web                                  # workbench at http://127.0.0.1:8765 (recommended)

# or CLI
trpgv voices                               # fetch edge-tts zh voices → assets/voices.json
trpgv all samples/xxx.txt -w work/xxx      # parse → clean → chars → script → audio
trpgv script -w work/xxx --scene 3         # rerun only scene 3 after review
trpgv assets -w work/xxx                   # auto-download missing SFX/BGM from Openverse
trpgv audio  -w work/xxx                   # remix (unchanged lines hit the cache)
```

Accepts `.txt` / `.docx`. Log lines look like `<[nickname]role>:text` (dice bot nickname contains "骰子"). Adjust the single regex in `src/trpgv/parse.py` for other exporters.

### Pipeline

| Step | Output | Notes |
|---|---|---|
| parse | `lines.jsonl` | pure code |
| clean | `clean.jsonl` / `drops.jsonl` | rule layer drops commands, bot chatter, OOC; folds dice rolls. LLM layer emits only `index reason` |
| chars | `characters.json` | KP split into narrator + NPCs, each with traits/tone/voice |
| script | `scenes/NN.md` + `script.md` | scene-by-scene rewrite; new NPCs tagged `【？name】` are auto-registered |
| audio | `out/NN_title.mp3` + `full.mp3` | edge-tts + pydub; BGM at -18 dB with fades |

### Layout

```
src/trpgv/      parse / clean / characters / script / tts / mix / assets / web / cli
prompts/        fixed LLM prefixes (prompt-cache friendly)
assets/         voices.json · tags.json (keyword→file) · sfx/ bgm/ (git-ignored, auto-fetched) · ATTRIBUTION.txt
docs/           requirements & design · dev plan with field notes (Chinese)
work/<project>/ run artifacts (git-ignored)
```

### Asset licensing

Files fetched by `trpgv assets` are CC0 / CC BY / CC BY-NC etc.; attribution lines are appended to `assets/ATTRIBUTION.txt`. Check each license before publishing (BY = credit, NC = non-commercial, ND = no derivatives).

## License

MIT
