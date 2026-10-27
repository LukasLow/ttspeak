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
$ ttspeak "Guten Morgen, wie geht es dir?"
$ ttspeak pull voxtral:4b
$ ttspeak list
$ ttspeak rm voxtral:4b
```

## Users and use cases

1. Speak a sentence from the terminal with one command, live-streamed by default.
2. Write a finished WAV or MP3 with `-o` for later use.
3. Declaratively install a TTS engine + model + voice through Home Manager.
4. Test several models and remove the ones that are not needed.
5. Clone a voice from a reference recording and manage it as a named profile.

## Command contract

| Command | Behaviour |
|---|---|
| `ttspeak TEXT...` | Synthesize text. Without `-o` and with playback enabled, stream chunks to the default audio device. With `-o`, write a file (non-streaming) and play it afterwards unless `--no-play`. |
| `ttspeak run MODEL TEXT...` | Same, with an explicit model. |
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
| `ttspeak runtime install [--python PATH] [--version V]` | Create the isolated MLX runtime venv. |
| `ttspeak runtime status` | Show runtime interpreter and whether `mlx_audio` imports. |
| `ttspeak doctor` | Check platform, store paths, runtime, default model. |
| `ttspeak version` | Print version. |

### Flags for synthesis

- `-m, --model ID`
- `--voice NAME` — preset speaker or cloned profile (a leading `@` forces profile lookup)
- `--emotion PRESET` — Qwen3 only: `neutral`, `happy`, `sad`, `angry`, `excited`, `calm`, `serious`, `whisper`
- `--instruct TEXT` — Qwen3 only: free-form style instruction (combines with `--emotion`)
- `--language NAME|CODE` — `de`/`German`, `en`/`English`, …
- `--speed FLOAT` — 0.5–2.0
- `-o, --output PATH` — write WAV/MP3/FLAC/OGG/Opus/M4A; disables live streaming
- `--play / --no-play` — live streaming by default when no `-o` is given
- `--engine mock|mlx` — `mock` is for development/tests only

`--` terminates flag parsing so text may start with a dash.

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
`mlx-audio[tts]` (with `mistral-common[audio]` for Voxtral) lives in the runtime
venv so the Nix package stays small, reproducible and buildable in the sandbox.

## Model registry (v0.1)

| ID | HF repo | Method |
|---|---|---|
| `voxtral:4b` | `mlx-community/Voxtral-4B-TTS-2603-mlx-4bit` | preset voices |
| `qwen3:0.6b` | `mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit` | custom voice |
| `qwen3:1.7b` | `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit` | custom voice |
| `qwen3:0.6b-base` | `mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit` | voice cloning |
| `qwen3:1.7b-base` | `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` | voice cloning |
| `qwen3:1.7b-design` | `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit` | voice design |

Voxtral voices: `de_female`, `de_male`, `casual_female`, `casual_male`,
`cheerful_female`, `neutral_female`, `neutral_male`, plus French, Spanish, Italian,
Portuguese, Dutch, Arabic and Hindi voices. Languages: English, French, Spanish,
German, Italian, Portuguese, Dutch, Arabic, Hindi.

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

1. `ttspeak "Hallo" --engine mock --no-play -o out.wav` creates a valid WAV.
2. `pull/list/show/rm/prune` work against a fake local registry with `file://` URLs;
   no network in tests.
3. Config precedence and emotion→instruct mapping are covered by tests.
4. Voice profile add/list/rm works and cloned voices force a Base model.
5. `pytest` passes inside `nix develop`.
6. `nix build` produces a working `ttspeak` binary with no Python deps.
7. README documents Home Manager usage, model management and removal.
8. Home Manager `onActivation.cleanup = "zap"` reconciles models and voices
   declaratively, including automatic removal of undeclared entries.
9. Without `-o`, MLX synthesis streams chunks to the audio device before the full
   text is generated; `request.stream` is true and `SpeakResult.output` is null.
10. With `-o`, generation is non-streaming and MP3 output is transcoded via ffmpeg;
    missing ffmpeg fails before model loading.

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
