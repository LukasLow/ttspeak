# ttspeak

[![Nix flake](https://img.shields.io/badge/Nix-flake-5277C3?logo=nixos&logoColor=white)](flake.nix)
[![Home Manager](https://img.shields.io/badge/Home%20Manager-module-5277C3)](nix/module.nix)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![macOS Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon-black?logo=apple&logoColor=white)](#requirements)

**Ollama-style local text-to-speech for Apple Silicon.** `ttspeak` is a small,
dependency-free CLI that manages [Voxtral](https://huggingface.co/mistralai/Voxtral-4B-TTS-2603)
and [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) models and voices, runs them
offline through [MLX Audio](https://github.com/Blaizzy/mlx-audio), and installs
declaratively with Nix / Home Manager. Live streaming and MP3 output are built in.

```console
$ ttspeak live "Guten Morgen, wie geht es dir?"
$ ttspeak save -o hallo.mp3 -t "Guten Morgen, wie geht es dir?"
$ ttspeak pull voxtral:4b
$ ttspeak list
$ ttspeak rm voxtral:4b
```

It is the missing `pull` / `list` / `rm` / `run` workflow for local TTS on macOS:
model weights live outside the Nix store, can be switched per command, and can be
removed without touching the installed software. Speech synthesis runs with
`HF_HUB_OFFLINE=1` against local weights — no text or audio is sent to a cloud.

## Why ttspeak?

- **Ollama-like UX for TTS.** `ttspeak live`, `save`, `pull`, `list`, `show`, `rm`,
  `prune` — familiar commands instead of Python snippets.
- **Local-first on Apple Silicon.** Voxtral and Qwen3-TTS through MLX Audio,
  optimized for M-series unified memory. No API key, no account, no upload.
- **Live audio by default.** `ttspeak live "Text"` streams to the speakers while it
  is being generated. `ttspeak save -o out.mp3 -t "Text"` writes a finished file
  without playback.
- **Declarative Nix / Home Manager.** Install the CLI, runtime, models and cloned
  voices from one configuration; `onActivation.cleanup = "zap"` removes everything
  that is no longer declared — the same idea as `homebrew.onActivation.cleanup`.
- **Small Nix package.** The CLI is pure Python standard library. `mlx-audio`
  lives in an isolated runtime venv, so the Nix build stays hermetic and fast.
- **Model and voice management.** Voxtral 4B (4/6-bit/bf16), all Qwen3-TTS
  variants (0.6B/1.7B, Base/CustomVoice/VoiceDesign, 4/6/8-bit/bf16), emotion/style
  instructions and cloned voice profiles.

## Requirements

- macOS on Apple Silicon (M1/M2/M3/M4/M5) for MLX synthesis.
- Nix with flakes and Home Manager (recommended), or Python 3.10+ for a manual
  install.
- ~2.5 GB disk for `voxtral:4b`, ~3.1 GB for `qwen3:1.7b`.
- `ffmpeg` for MP3/FLAC/OGG/Opus/M4A output (the Home Manager module installs it).

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
  # === Home Manager: local speech output (Voxtral + Qwen3-TTS via MLX) ===
  home-manager.sharedModules = [
    {
      imports = [ inputs.ttspeak.homeManagerModules.default ];

      programs.ttspeak = {
        enable = true;

        # Declarative defaults. `ttspeak config set ...` can override them at
        # runtime; the user config has the final say.
        settings = {
          model = "voxtral:4b";
          language = "auto";
          default_gender = "female";
          speed = 1.0;

          # Each language has its own voice. A short alias points at the
          # concrete voice, which points at the model:
          #   de -> de_female -> { model = "voxtral:4b"; voice = "de_female"; }
          voices = {
            de = "de_female";
            de_female = { model = "voxtral:4b"; voice = "de_female"; };
            de_male = { model = "voxtral:4b"; voice = "de_male"; };

            en = "en_female";
            en_female = { model = "voxtral:4b"; voice = "it_female"; };
            en_male = { model = "voxtral:4b"; voice = "casual_male"; };

            ru = "ru_female";
            ru_female = { model = "qwen3:1.7b"; voice = "Sohee"; };
            ru_male = { model = "qwen3:1.7b"; voice = "Dylan"; };
          };
        };

        # Installed on switch (idempotent, only when missing).
        models = [
          "voxtral:4b"
          "qwen3:1.7b"
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

`settings.voices` is a flat alias map: a short language alias points at a concrete
voice, and the concrete voice points at a model. `de -> de_female -> voxtral:4b /
de_female` is the same pattern for every language. If `de` is not declared, the
generic fallback is `de_<default_gender>`; `default_gender` is only a fallback and
not a global rule. Use `de_male`, `en_male`, `ru_male` for the male variants.
The `settings` option accepts nested attrsets and lists for this mapping.

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
| `programs.ttspeak.ffmpeg` | `true` | Install ffmpeg for MP3/FLAC/OGG/Opus/M4A output. |
| `programs.ttspeak.onActivation.cleanup` | `"none"` | `"none"` or `"zap"` (remove undeclared models/voices). |
| `programs.ttspeak.onActivation.failOnError` | `false` | Fail the switch on pull/runtime errors. |

## Quick start (without Home Manager)

```console
$ nix run github:LukasLow/ttspeak -- runtime install
$ nix run github:LukasLow/ttspeak -- pull voxtral:4b
$ nix run github:LukasLow/ttspeak -- live "Hallo, das ist ein lokaler TTS-Test."
```

For permanent use, install the CLI into a profile:

```console
$ nix profile install github:LukasLow/ttspeak
$ ttspeak runtime install
$ ttspeak pull voxtral:4b
$ ttspeak live "Hallo, das ist ein lokaler TTS-Test."
$ ttspeak save -o hallo.mp3 -t "Hallo, das ist ein lokaler TTS-Test."
```

## Commands

```console
ttspeak live "Text" [flags]                  # stream to speakers
ttspeak save -o hallo.mp3 -t "Text" [flags]  # write a file, no playback
ttspeak run voxtral:4b "Text"                # live with an explicit model
ttspeak pull voxtral:4b                      # download weights
ttspeak list                                 # installed models
ttspeak search voxtral                       # all registry variants
ttspeak show voxtral:4b                      # details, voices, languages
ttspeak rm voxtral:4b                        # remove weights (asks)
ttspeak prune --keep voxtral:4b --yes        # remove everything else
ttspeak voices                               # preset + cloned voices
ttspeak voice add NAME --audio ref.wav --text "transcript" --model qwen3:0.6b-base
ttspeak voice rm NAME
ttspeak voice prune --keep NAME --yes         # remove undeclared profiles
ttspeak config set language auto
ttspeak config set voice de_male
ttspeak config list
ttspeak runtime install
ttspeak runtime status
ttspeak doctor
```

### Synthesis flags

`live` and `run` stream by default. `save` never plays unless `--play` is given.

| Flag | Meaning |
|---|---|
| `-m, --model ID` | Model id (default: `voxtral:4b`). |
| `-v, --voice NAME` | Language alias (`de`, `en`, `ru`), concrete voice (`de_male`) or cloned profile (`@name`). |
| `--emotion NAME` | Qwen3 only: `neutral`, `happy`, `sad`, `angry`, `excited`, `calm`, `serious`, `whisper`. |
| `--instruct TEXT` | Qwen3 only: free-form style instruction, combined with `--emotion`. |
| `--language LANG` | `auto` (default) or `de`/`German`, `en`/`English`, `ru`/`Russian`, … (model-dependent). |
| `--speed FLOAT` | `0.5` … `2.0` (model-dependent). |
| `--engine mlx\|mock` | Backend. `mock` writes a tone without MLX. |
| `--json` | Machine-readable result. |

`save` requires `-o/--output` and `-t/--text`. Formats: WAV, MP3, FLAC, OGG,
Opus, M4A. `--play` plays the finished file after writing.

### Automatic language detection

`--language auto` is the default. Input is split into sentences (and Cyrillic/Latin
script runs) and each segment is detected as German, English or Russian. Each
detected language uses its own configured voice and model. Unknown Latin text falls
back to German.

```console
# One save file, three voices/models
ttspeak save -o mixed.mp3 -t "Guten Abend. Good evening. Добрый вечер."

# One live listening stream, sequential per segment
ttspeak live "Guten Abend. Good evening. Добрый вечер."

# Force one configured voice for the whole input
ttspeak live "Guten Abend. Good evening." -v de

# Force one language and its configured voice
ttspeak live "Good evening." --language en
```

`save` always writes **one** file. `live` always plays **one** sequential stream;
model changes between segments can cause a short loading gap. For a single-language
input there is no extra segmentation.

Examples:

```console
ttspeak live "Das ist unglaublich!" --emotion excited       # Qwen3 model
ttspeak live "Willkommen zurück." -v de
ttspeak live "Willkommen zurück." -v de_male
ttspeak save -o willkommen.mp3 -t "Willkommen zurück." -v de
ttspeak save -o hallo.wav -t "Hallo"                        # save only, no playback
ttspeak live "Hallo" -v @lukas
```

Without `-o`, audio is streamed to the speakers as it is generated. With `-o`, the
file is written completely first (no streaming). `--no-play` without `-o` writes a
timestamped WAV under `~/Library/Application Support/ttspeak/output/` on macOS.
`afplay` is used for file playback; if no player is found the file is kept.

## Models

The registry tracks **all** available MLX variants of Voxtral and Qwen3-TTS.
`ttspeak search` lists them; the base id is the 8-bit variant for Qwen3 and the
4-bit variant for Voxtral.

| Family | IDs | Size |
|---|---|---|
| Voxtral 4B TTS | `voxtral:4b` (4-bit), `voxtral:4b-6bit`, `voxtral:4b-bf16` | ~2.5 / 3.5 / 8 GB |
| Qwen3-TTS 0.6B CustomVoice | `qwen3:0.6b`, `qwen3:0.6b-4bit`, `qwen3:0.6b-6bit`, `qwen3:0.6b-bf16` | ~2 GB |
| Qwen3-TTS 1.7B CustomVoice | `qwen3:1.7b`, `qwen3:1.7b-4bit`, `qwen3:1.7b-6bit`, `qwen3:1.7b-bf16` | ~3–3.5 GB |
| Qwen3-TTS 0.6B Base (cloning) | `qwen3:0.6b-base`, `-4bit`, `-6bit`, `-bf16` | ~2 GB |
| Qwen3-TTS 1.7B Base (cloning) | `qwen3:1.7b-base`, `-4bit`, `-6bit`, `-bf16` | ~3–3.5 GB |
| Qwen3-TTS 1.7B VoiceDesign | `qwen3:1.7b-design`, `-4bit`, `-6bit`, `-bf16` | ~3–3.5 GB |

Voxtral voices: `de_female`, `de_male`, `casual_female`, `casual_male`,
`cheerful_female`, `neutral_female`, `neutral_male`, `fr_female`, `fr_male`,
`es_female`, `es_male`, `it_female`, `it_male`, `pt_female`, `pt_male`,
`nl_female`, `nl_male`, `ar_male`, `hi_female`, `hi_male`.

Qwen3 speakers: `Vivian`, `Serena`, `Uncle_Fu`, `Dylan`, `Eric`, `Ryan`, `Aiden`,
`Ono_Anna`, `Sohee`.

`voxtral` is an alias for `voxtral:4b`, `qwen3` for `qwen3:0.6b`. Full Hugging
Face repo ids are accepted too.

### German, English and Russian

| Language | Voxtral 4B | Qwen3-TTS |
|---|---|---|
| German | Yes (`de_female`, `de_male`, …) | Yes (all 9 voices) |
| English | Yes (all 20 voices) | Yes (all languages/voices) |
| Russian | **No** (not supported by Voxtral TTS) | Yes |

Use `--language de`, `--language en`, `--language ru` (or `German`, `English`,
`Russian`). German sentences in this README are example *input text*, not
documentation language; the repository documentation and comments are English.

## Voice cloning

```console
$ ttspeak pull qwen3:0.6b-base
$ ttspeak voice add lukas --audio ~/stimme.wav --text "Der exakte Text der Aufnahme."
$ ttspeak live "Das ist meine geklonte Stimme." --voice lukas
```

Voice cloning is a Qwen3-TTS Base feature; Voxtral uses its 20 preset voices.
Use a clean 5–15 second WAV and the exact transcript. The profile stores a copy of
the reference audio plus the transcript under the data root; `ttspeak voice rm lukas`
removes it without touching the base model. In Home Manager, declare the same profile
under `programs.ttspeak.voices` so it is recreated reproducibly.

## Storage and removal

```
~/Library/Application Support/ttspeak/
  config.json          mutable user config
  models/<id>/         weights + .ttspeak-manifest.json
  voices/<name>/       profile.json + reference.wav
  runtime/venv/        isolated mlx-audio environment
  output/              fallback audio when `run` is used without a file
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
                                     └─ mlx-audio[tts] + Voxtral/Qwen3 (local weights)
```

The CLI has no Python dependencies. `mlx-audio[tts]` (including
`mistral-common[audio]` for Voxtral), MLX and their transitive dependencies live in
a runtime venv at `<data root>/runtime/venv`, created by `ttspeak runtime install`
(or by Home Manager). Synthesis runs with `HF_HUB_OFFLINE=1`; all weights are loaded
from the local model directory, so no text or audio leaves the machine.

Without `-o`, the worker generates with `stream=True` and writes chunks to the
default CoreAudio device via `sounddevice`; the first audio arrives before the text
is fully processed. With `-o`, generation is non-streaming and the finished WAV is
optionally transcoded with ffmpeg.

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

### Voice tournament (local dev helper)

The generated audio and HTML stay out of git (`tournament/` is ignored).

```console
$ nix develop --command python tools/tournament.py       # audio + voices.html
$ nix develop --command python tools/blind_tournament.py # six blind A/B brackets
$ open tournament/blind.html
```

The blind page compares two samples at a time, hides names until a bracket is
complete, and produces a copyable result text for German/English/Russian female
and male winners. Voxtral has no Russian support, so the Russian brackets are
Qwen3-TTS only.

```console
$ nix run .# -- "Hallo" --engine mock --no-play -o /tmp/hallo.wav
```

## Limitations

- MLX synthesis only on macOS Apple Silicon.
- Non-WAV output requires `ffmpeg` (installed by the Home Manager module by default).
- `live` streams; `save` writes a file. There is no bare `ttspeak "Text"` shortcut.
- Voxtral TTS does not support Russian; use Qwen3-TTS for Russian.
- Emotion/style instructions are model-dependent and available on Qwen3-TTS;
  Voxtral uses its preset voices instead.
- No HTTP server, no non-MLX engines.
- The registry is pinned in this repository; updating it ships with a new release.

## License

The **ttspeak code** is MIT licensed.

Model weights have their own licenses: Qwen3-TTS is Apache-2.0; **Voxtral TTS is
CC-BY-NC-4.0 (non-commercial use)**. Check the model card before commercial use.
