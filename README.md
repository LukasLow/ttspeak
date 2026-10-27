# ttspeak

[![Nix flake](https://img.shields.io/badge/Nix-flake-5277C3?logo=nixos&logoColor=white)](flake.nix)
[![Home Manager](https://img.shields.io/badge/Home%20Manager-module-5277C3)](nix/module.nix)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![macOS Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon-black?logo=apple&logoColor=white)](#requirements)

**Ollama-style local text-to-speech for Apple Silicon.** `ttspeak` is a small,
dependency-free CLI that manages [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
models and voices, runs them offline through
[MLX Audio](https://github.com/Blaizzy/mlx-audio), and installs declaratively with
Nix / Home Manager.

```console
$ ttspeak "Guten Morgen, wie geht es dir?"
$ ttspeak pull qwen3:0.6b
$ ttspeak list
$ ttspeak rm qwen3:0.6b
```

It is the missing `pull` / `list` / `rm` / `run` workflow for local TTS on macOS:
model weights live outside the Nix store, can be switched per command, and can be
removed without touching the installed software. Speech synthesis runs with
`HF_HUB_OFFLINE=1` against local weights — no text or audio is sent to a cloud.

## Why ttspeak?

- **Ollama-like UX for TTS.** `ttspeak "Text"`, `pull`, `list`, `show`, `rm`,
  `prune`, `run` — familiar commands instead of Python snippets.
- **Local-first on Apple Silicon.** Qwen3-TTS through MLX Audio, optimized for
  M-series unified memory. No API key, no account, no upload.
- **Declarative Nix / Home Manager.** Install the CLI, runtime, models and cloned
  voices from one configuration; `onActivation.cleanup = "zap"` removes everything
  that is no longer declared — the same idea as `homebrew.onActivation.cleanup`.
- **Small Nix package.** The CLI is pure Python standard library. `mlx-audio`
  lives in an isolated runtime venv, so the Nix build stays hermetic and fast.
- **Model and voice management.** Five Qwen3-TTS variants, nine preset speakers,
  ten languages, emotion/style instructions and cloned voice profiles.

## Requirements

- macOS on Apple Silicon (M1/M2/M3/M4/M5) for MLX synthesis.
- Nix with flakes and Home Manager (recommended), or Python 3.10+ for a manual
  install.
- ~2 GB disk for `qwen3:0.6b`, ~3.1 GB for the 1.7B variants.

The `mock` engine works everywhere and is used by the test suite; Linux users can
develop and test the CLI, but real speech needs Apple Silicon.

## Install with Nix / Home Manager

The examples below match a nix-darwin setup with `home-manager.sharedModules`
(the layout used by `~/nix-config`).

### 1. Add the flake input

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:nixOS/nixpkgs/nixpkgs-unstable";

    # ...

    ttspeak.url = "github:LukasLow/ttspeak";
    ttspeak.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nix-darwin, ... }@inputs: {
    # ...
  };
}
```

### 2. Add a tool module

```nix
# programs/tools/ttspeak.nix
{ inputs, ... }: {
  # === Home-Manager: lokale Sprachausgabe (Qwen3-TTS via MLX) ===
  home-manager.sharedModules = [
    {
      imports = [ inputs.ttspeak.homeManagerModules.default ];

      programs.ttspeak = {
        enable = true;

        # Declarative defaults. `ttspeak config set ...` can override them at
        # runtime; the user config has the final say.
        settings = {
          model = "qwen3:0.6b";
          voice = "Serena";
          language = "German";
          speed = 1.0;
        };

        # Installed on switch (idempotent, only when missing).
        models = [
          "qwen3:0.6b"
          "qwen3:0.6b-base"
        ];

        # Optional: declare a cloned voice. Its base model is pulled
        # automatically.
        voices.lukas = {
          audio = ./voices/lukas.wav;
          text = "The exact transcript of the reference recording.";
          model = "qwen3:0.6b-base";
        };

        # Like `homebrew.onActivation.cleanup = "zap"`: remove everything that
        # is not declared here. The default is "none".
        onActivation.cleanup = "zap";
      };
    }
  ];
}
```

### 3. Import the module

```nix
# programs/tools/+defaults.nix
{ ... }: {
  imports = [
    ./ollama.nix
    ./opencode.nix
    ./ttspeak.nix
  ];
}
```

Then rebuild as usual (`up-darwin` / `darwin-rebuild switch`). On activation
ttspeak installs the isolated MLX runtime if needed, pulls the declared models and
creates the declared voice profiles.

### What `cleanup = "zap"` does

| Declared in Home Manager | Result on switch |
|---|---|
| `models = [ "qwen3:0.6b" ]` | pulls it if missing, keeps it |
| a model installed manually but not listed | **removed** |
| `voices.lukas = { ... }` | creates/updates the profile, pulls its base model |
| a profile created with `ttspeak voice add` but not listed | **removed** |
| `onActivation.cleanup = "none"` | installs/updates only, never deletes |

`cleanup = "none"` is the safe default. Set `"zap"` when the configuration should be
the single source of truth. Network failures only warn by default; set
`onActivation.failOnError = true` to fail the switch instead.

### Module options

| Option | Default | Meaning |
|---|---|---|
| `programs.ttspeak.enable` | `false` | Install the CLI and activation steps. |
| `programs.ttspeak.package` | this flake's package | Package to install. |
| `programs.ttspeak.settings` | `{}` | Declarative defaults, exported as `TTSPEAK_DEFAULTS`. |
| `programs.ttspeak.models` | `[]` | Models pulled on activation. |
| `programs.ttspeak.voices.<name>` | `{}` | Cloned voice profiles (`audio`, `text`, `model`). |
| `programs.ttspeak.runtime.enable` | `true` | Create the MLX runtime if missing. |
| `programs.ttspeak.runtime.version` | `null` | Pin an `mlx-audio` version. |
| `programs.ttspeak.onActivation.cleanup` | `"none"` | `"none"` or `"zap"` (remove undeclared models/voices). |
| `programs.ttspeak.onActivation.failOnError` | `false` | Fail the switch on pull/runtime errors. |

## Quick start (without Home Manager)

```console
$ nix run github:LukasLow/ttspeak -- runtime install
$ nix run github:LukasLow/ttspeak -- pull qwen3:0.6b
$ nix run github:LukasLow/ttspeak -- "Hallo, das ist ein lokaler TTS-Test."
```

For permanent use, install the CLI into a profile:

```console
$ nix profile install github:LukasLow/ttspeak
$ ttspeak runtime install
$ ttspeak pull qwen3:0.6b
$ ttspeak "Hallo, das ist ein lokaler TTS-Test."
```

## Commands

```console
ttspeak "Text" [flags]                 # speak
ttspeak run qwen3:0.6b "Text"          # explicit model
ttspeak pull qwen3:1.7b                # download weights
ttspeak list                           # installed models
ttspeak search qwen                    # registry
ttspeak show qwen3:0.6b                # details, voices, languages
ttspeak rm qwen3:1.7b                  # remove weights (asks)
ttspeak prune --keep qwen3:0.6b --yes  # remove everything else
ttspeak voices                         # preset + cloned voices
ttspeak voice add NAME --audio ref.wav --text "transcript" --model qwen3:0.6b-base
ttspeak voice rm NAME
ttspeak voice prune --keep NAME --yes       # remove undeclared profiles
ttspeak config set voice Ryan
ttspeak config list
ttspeak runtime install
ttspeak runtime status
ttspeak doctor
```

### Synthesis flags

| Flag | Meaning |
|---|---|
| `-m, --model ID` | Model id. |
| `--voice NAME` | Preset speaker or cloned profile (`@name` forces profile lookup). |
| `--emotion NAME` | `neutral`, `happy`, `sad`, `angry`, `excited`, `calm`, `serious`, `whisper`. |
| `--instruct TEXT` | Free-form style instruction, combined with `--emotion`. |
| `--language LANG` | `de`/`German`, `en`/`English`, `fr`, `es`, `it`, `pt`, `ru`, `ja`, `ko`, `zh`. |
| `--speed FLOAT` | `0.5` … `2.0`. |
| `-o, --output FILE.wav` | Save audio (default: timestamped file under the data root). |
| `--play` / `--no-play` | Playback (default: on). |
| `--engine mlx\|mock` | Backend. `mock` writes a tone without MLX. |
| `--json` | Machine-readable result. |

Examples:

```console
ttspeak "Das ist unglaublich!" --emotion excited
ttspeak "Willkommen zurück." --voice Ryan --language de -o willkommen.wav
ttspeak "Bitte langsam." --speed 0.85 --instruct "ruhig und warm"
ttspeak "Hallo" --voice @lukas
```

The default output goes to `~/Library/Application Support/ttspeak/output/` on macOS.
`afplay` is used for playback; if no player is found the file is kept.

## Models

| ID | Size (8-bit) | Purpose |
|---|---|---|
| `qwen3:0.6b` | ~2.0 GB | Default. Preset voices + emotion. |
| `qwen3:1.7b` | ~3.1 GB | Better emotion control. |
| `qwen3:0.6b-base` | ~2.0 GB | Voice cloning. |
| `qwen3:1.7b-base` | ~3.1 GB | Higher-quality cloning. |
| `qwen3:1.7b-design` | ~3.1 GB | Design a voice from a text description. |

Preset speakers: `Vivian`, `Serena`, `Uncle_Fu`, `Dylan`, `Eric`, `Ryan`, `Aiden`,
`Ono_Anna`, `Sohee`. Languages: Chinese, English, Japanese, Korean, German, French,
Russian, Portuguese, Spanish, Italian.

`qwen3` is an alias for `qwen3:0.6b`. Full Hugging Face repo ids are accepted too.

### German text-to-speech, offline

German is a first-class synthesis language: use `--language de` (or
`language = "German"` in Home Manager). All Qwen3-TTS preset voices are
multilingual; `Serena` (warm female), `Ryan` (dynamic male) and `Vivian` (bright
female) are good starting points for German. Voice cloning also works with a
German reference recording and its exact transcript.

German sentences in this README are example *input text*, not documentation
language; the repository documentation and comments are English.

## Voice cloning

```console
$ ttspeak pull qwen3:0.6b-base
$ ttspeak voice add lukas --audio ~/stimme.wav --text "Der exakte Text der Aufnahme."
$ ttspeak "Das ist meine geklonte Stimme." --voice lukas
```

Use a clean 5–15 second WAV and the exact transcript. The profile stores a copy of the
reference audio plus the transcript under the data root; `ttspeak voice rm lukas`
removes it without touching the base model. In Home Manager, declare the same profile
under `programs.ttspeak.voices` so it is recreated reproducibly.

## Storage and removal

```
~/Library/Application Support/ttspeak/
  config.json          mutable user config
  models/<id>/         weights + .ttspeak-manifest.json
  voices/<name>/       profile.json + reference.wav
  runtime/venv/        isolated mlx-audio environment
  output/              default generated WAVs
```

- `ttspeak rm MODEL` deletes one model's weights.
- `ttspeak prune --keep ...` deletes models not in the keep list.
- `ttspeak voice rm NAME` deletes a cloned voice.
- `programs.ttspeak.onActivation.cleanup = "zap"` reconciles both lists on every
  switch, like `brew bundle cleanup --force`.
- Removing `programs.ttspeak.enable` removes the CLI. **Weights are data and are not
  deleted by Nix itself.** Use `zap`, `ttspeak rm`, or `ttspeak prune` beforehand.
- Nix never manages the weights; changing the package does not re-download a model.

### Environment

| Variable | Meaning |
|---|---|
| `TTSPEAK_HOME` | Data root (default: macOS Application Support / XDG data dir). |
| `TTSPEAK_DEFAULTS` | Declarative defaults JSON (set by Home Manager). |
| `TTSPEAK_MODEL`, `TTSPEAK_VOICE`, `TTSPEAK_LANGUAGE`, `TTSPEAK_EMOTION`, `TTSPEAK_SPEED`, `TTSPEAK_PLAY` | Override individual settings. |
| `TTSPEAK_ENGINE` | `mlx` or `mock`. |
| `TTSPEAK_PYTHON` | Explicit Python interpreter for the MLX worker. |
| `TTSPEAK_REGISTRY` | Alternative model registry (mainly for tests). |
| `HF_TOKEN` | Hugging Face token for gated downloads. |

## How it works

```
ttspeak (stdlib-only Python CLI, installed by Nix)
   ├─ model store: Hugging Face API + resumable downloads + SHA-256 checks
   ├─ config / voice profiles
   └─ mlx engine ── subprocess ──> isolated runtime Python
                                     └─ mlx-audio + Qwen3-TTS (local weights)
```

The CLI has no Python dependencies. `mlx-audio`, MLX and their transitive dependencies
live in a runtime venv at `<data root>/runtime/venv`, created by
`ttspeak runtime install` (or by Home Manager). Synthesis runs with `HF_HUB_OFFLINE=1`;
all weights are loaded from the local model directory, so no text or audio leaves the
machine.

`pull` uses the Hugging Face REST API (`?blobs=true`), resumes partial downloads, checks
file sizes and validates SHA-256 for LFS files before atomically renaming the model
directory into place. Set `HF_TOKEN` for gated repositories.

## Development

```console
$ nix develop
$ pytest
$ ruff check .
$ nix build
$ ./result/bin/ttspeak --version
```

The test suite is hermetic: it uses a fake registry with `file://` URLs and the `mock`
engine, so no network, model download or GPU is required.

```console
$ nix run .# -- "Hallo" --engine mock --no-play -o /tmp/hallo.wav
```

## Limitations

- MLX synthesis only on macOS Apple Silicon.
- WAV output only in v0.1 (MP3/FLAC would need ffmpeg).
- No streaming, no HTTP server, no non-Qwen engines.
- Emotion/style instructions are model-dependent; `--emotion` is a mapping to Qwen3
  style instructions, not a guaranteed deterministic control.
- The registry is pinned in this repository; updating it ships with a new release.

## License

MIT
