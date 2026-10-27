# ttspeak — Specification (v0.1)

## Problem

Ollama made local LLMs manageable: one CLI, a model store, `pull`, `list`, `rm`.
Local TTS on Apple Silicon has no equivalent. Voxtral and Qwen3-TTS via
`mlx-audio` are strong engines, but installing them, downloading weights, choosing
a voice and removing them again is manual work.

## Goal

`ttspeak` is an Ollama-style command line tool for local text-to-speech on macOS
(Apple Silicon), installed and configured with Nix / Home Manager.

```console
$ ttspeak live "Guten Morgen, wie geht es dir?"
$ ttspeak save -o hallo.mp3 -t "Guten Morgen, wie geht es dir?"
$ ttspeak pull voxtral:4b
$ ttspeak list
$ ttspeak rm voxtral:4b
```

## Users and use cases

1. Speak a sentence from the terminal with one command, live-streamed by default.
2. Write a finished WAV or MP3 with `save` for later use.
3. Declaratively install a TTS engine + model + voice through Home Manager.
4. Test several models and remove the ones that are not needed.
5. Clone a voice from a reference recording and manage it as a named profile.

## Command contract

| Command | Behaviour |
|---|---|
| `ttspeak live TEXT...` | Synthesize text and stream chunks to the default audio device. No file is written. |
| `ttspeak save -o PATH -t TEXT` | Synthesize a finished file (WAV/MP3/FLAC/OGG/Opus/M4A) without playback. `--play` plays it after writing. |
| `ttspeak run MODEL TEXT...` | Live with an explicit model; `-o` writes a file and plays it unless `--no-play`. |
| `ttspeak pull MODEL [--force]` | Download a registry model into the local store, atomically. |
| `ttspeak list` | Installed models, size, default marker. |
| `ttspeak search [QUERY]` | Registry models with installed marker. |
| `ttspeak show MODEL` | Metadata, voices, languages, install state, path. |
| `ttspeak rm MODEL [--yes]` | Remove model weights. Warns if a voice profile uses the model. |
| `ttspeak prune --keep ID... [--yes]` | Remove installed models that are not in the keep list. |
| `ttspeak voices` | Preset voices + cloned voice profiles. |
| `ttspeak voice add NAME --audio FILE --text TRANSCRIPT [--model BASE]` | Create a cloned-voice profile. |
| `ttspeak voice rm NAME [--yes]` | Remove a voice profile (never a preset voice). |
| `ttspeak voice show NAME` | Profile details. |
| `ttspeak voice prune --keep NAME... [--yes]` | Remove profiles not in the keep list. |
| `ttspeak config get/set/unset/list` | Mutable user configuration. |
| `ttspeak runtime install [--python PATH] [--version V]` | Create or repair the isolated MLX runtime venv. |
| `ttspeak runtime status` | Show runtime interpreter, `mlx-audio` and `mistral-common` versions. |
| `ttspeak doctor` | Check platform, store paths, runtime, default model. |
| `ttspeak version` | Print version. |

### Flags for synthesis

- `-m, --model ID`
- `--voice NAME` — preset speaker or cloned profile (a leading `@` forces profile lookup)
- `--emotion PRESET` — Qwen3 only: `neutral`, `happy`, `sad`, `angry`, `excited`, `calm`, `serious`, `whisper`
- `--instruct TEXT` — Qwen3 only: free-form style instruction (combines with `--emotion`)
- `--language NAME|CODE` — `de`/`German`, `en`/`English`, `ru`/`Russian`, …
- `--speed FLOAT` — 0.5–2.0
- `save`: `-o, --output PATH` and `-t, --text TEXT` are required; `--play` is optional
- `live`/`run`: no output path; audio streams live
- `run`: `-o` writes a file and plays it unless `--no-play`
- `--engine mock|mlx` — `mock` is for development/tests only

`live --` terminates flag parsing so text may start with a dash.

## Storage layout

Root: `$TTSPEAK_HOME`, default:
- macOS: `~/Library/Application Support/ttspeak`
- Linux: `$XDG_DATA_HOME/ttspeak` or `~/.local/share/ttspeak`

```
<root>/
  config.json                 mutable user config
  models/<slug>/              downloaded weights + .ttspeak-manifest.json
  voices/<slug>/              profile.json + reference.wav
  runtime/venv/               isolated Python env with mlx-audio
  output/                     default generated audio (timestamped)
```

Model weights are never placed in the Nix store. They are data, managed by `pull`/`rm`.

## Configuration precedence

CLI flag > environment > user config (`config.json`) > declarative defaults
(`$TTSPEAK_DEFAULTS`, written by Home Manager) > built-in defaults.

Environment: `TTSPEAK_HOME`, `TTSPEAK_DEFAULTS`, `TTSPEAK_MODEL`, `TTSPEAK_VOICE`,
`TTSPEAK_LANGUAGE`, `TTSPEAK_EMOTION`, `TTSPEAK_SPEED`, `TTSPEAK_ENGINE`,
`TTSPEAK_PYTHON`, `TTSPEAK_REGISTRY`, `HF_TOKEN`.

Built-in defaults: model `voxtral:4b`, voice = model default (`de_female` for
Voxtral), language `German`, speed `1.0`, play enabled.

## Backends

- **Mock** (`--engine mock`): pure standard library; writes a deterministic tone
  WAV. Used by the test suite and for development on non-Apple hardware.
- **MLX** (default on macOS arm64): invokes an isolated runtime Python with
  `worker_mlx.py`. The worker loads the *local* model directory with
  `mlx_audio.tts.utils.load_model` (no Hub access at synthesis time) and calls
  `generate` (Voxtral preset voices or Qwen3 cloning), `generate_custom_voice`
  or `generate_voice_design`. With `stream=True` it writes chunks directly to the
  default audio device via `sounddevice` (live mode); otherwise it writes a 16-bit
  PCM WAV. Communication is JSON in / JSON out over files.

The core CLI has **zero Python dependencies** (standard library only).
`mlx-audio[tts]==0.6.2` and `mistral-common[audio]==1.12.0` live in the runtime
venv so the Nix package stays small, reproducible and buildable in the sandbox.

## Model registry (v0.1)

All available MLX variants are tracked (23 models):

| Family | IDs | Method |
|---|---|---|
| Voxtral 4B | `voxtral:4b` (4-bit), `-6bit`, `-bf16` | preset voices |
| Qwen3-TTS 0.6B CustomVoice | `qwen3:0.6b` (8-bit), `-4bit`, `-6bit`, `-bf16` | custom voice |
| Qwen3-TTS 1.7B CustomVoice | `qwen3:1.7b` (8-bit), `-4bit`, `-6bit`, `-bf16` | custom voice |
| Qwen3-TTS 0.6B Base | `qwen3:0.6b-base` (8-bit), `-4bit`, `-6bit`, `-bf16` | voice cloning |
| Qwen3-TTS 1.7B Base | `qwen3:1.7b-base` (8-bit), `-4bit`, `-6bit`, `-bf16` | voice cloning |
| Qwen3-TTS 1.7B VoiceDesign | `qwen3:1.7b-design` (8-bit), `-4bit`, `-6bit`, `-bf16` | voice design |

Voxtral voices: `de_female`, `de_male`, `casual_female`, `casual_male`,
`cheerful_female`, `neutral_female`, `neutral_male`, plus French, Spanish, Italian,
Portuguese, Dutch, Arabic and Hindi voices. Languages: English, French, Spanish,
German, Italian, Portuguese, Dutch, Arabic, Hindi. **No Russian.**

Qwen3 speakers: Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna, Sohee.
Languages: Chinese, English, Japanese, Korean, German, French, Russian, Portuguese,
Spanish, Italian.

`pull` uses the Hugging Face REST API (`?blobs=true`), downloads files with resume,
checks sizes and (for LFS files) SHA-256, then renames the temp directory into place.

## Nix deliverables

- `packages.<system>.default` — the pure-Python CLI (`buildPythonApplication`).
- `devShells.<system>.default` — Python, pytest, uv, ruff and ffmpeg.
- `homeManagerModules.default` — `programs.ttspeak`:
  - installs the package and ffmpeg (optional, default on),
  - writes declarative defaults from `settings` via `TTSPEAK_DEFAULTS`,
  - pulls `models` on activation (idempotent, non-fatal warnings),
  - optionally creates `voices.<name>` profiles from reference audio and pulls
    their base models,
  - `onActivation.cleanup = "zap"` removes models/voices not declared
    (the `brew bundle cleanup --force` equivalent); default is `"none"`,
  - optionally installs the MLX runtime (`mlx-audio[tts]`, uv + Python).

## Acceptance criteria

1. `ttspeak save --engine mock -o out.wav -t "Hallo"` creates a valid WAV.
2. `pull/list/show/rm/prune` work against a fake local registry with `file://` URLs;
   no network in tests.
3. Config precedence and emotion→instruct mapping are covered by tests.
4. Voice profile add/list/rm works and cloned voices force a Base model.
5. `pytest` passes inside `nix develop`.
6. `nix build` produces a working `ttspeak` binary with no Python deps.
7. README documents Home Manager usage, model management and removal.
8. Home Manager `onActivation.cleanup = "zap"` reconciles models and voices
   declaratively, including automatic removal of undeclared entries.
9. `ttspeak live` streams chunks to the audio device before the full text is
   generated; `SpeakResult.output` is null.
10. `ttspeak save -o out.mp3 -t ...` is non-streaming and transcodes via ffmpeg;
    missing ffmpeg fails before model loading.
11. `ttspeak "Hallo"` is rejected with a hint to use `live` or `save`.

## Boundaries

- **Always**: keep the CLI dependency-free; store weights outside the Nix store;
  confirm destructive removal unless `--yes`; keep tests hermetic.
- **Ask first**: adding a new runtime dependency, changing the on-disk format in a
  breaking way, deleting user voice recordings automatically.
- **Never**: send text or audio to a cloud service; auto-delete unlisted data unless
  the user opted into pruning; store secrets in the Nix store or config output.

## Non-goals (v0.1)

HTTP server/API, non-MLX engines, Linux MLX, automatic speech recognition of
reference audio.
