# AGENTS.md — ttspeak

## Language policy

- **English only** for everything that describes or maintains the repository:
  README, SPEC, AGENTS.md, docs, code comments, Nix comments, test names,
  commit messages, CLI help, error messages and GitHub metadata.
- **German is a supported product language.** German example sentences, voice
  transcripts, test phrases and German TTS output are explicitly allowed and
  should not be removed or "translated away". The project must keep working
  offline for German text (`--language de` / `German`).
- When in doubt: documentation/comments in English, synthesized content and
  user-facing examples may be German.

## What this project is

`ttspeak` is an Ollama-style CLI for local text-to-speech on macOS Apple Silicon.
It manages Voxtral and Qwen3-TTS model weights plus cloned voice profiles, and
delegates synthesis to MLX Audio in an isolated runtime venv. The default model
is Voxtral 4B (4-bit) with the German `de_female` voice; Qwen3-TTS remains
available for emotion control and voice cloning.

## Architecture rules

- The installed CLI (`src/ttspeak`) must stay **Python standard library only**.
  Do not add runtime dependencies to `pyproject.toml`.
- `mlx-audio`, MLX and model weights are runtime data, not part of the Nix
  package or the Nix store.
- Model weights live under `$TTSPEAK_HOME/models`; generated audio under
  `output/`; cloned voices under `voices/`.
- All synthesis must work offline (`HF_HUB_OFFLINE=1`). Never send text or audio
  to a cloud service.
- Destructive commands (`rm`, `prune`, `voice rm`) require `--yes` in
  non-interactive shells.
- Home Manager `onActivation.cleanup = "zap"` is the declarative equivalent of
  `brew bundle cleanup --force`: install declared models/voices, remove the rest.
  Keep `"none"` as the safe default.

## Code and Nix style

- 2-space indentation, trailing newline, English comments.
- Nix files follow the structure of the user's `~/nix-config`:
  small modules, section comments like `# === Packages ===`, `let ... in`
  bindings, no `flake-utils`.
- Keep the README example aligned with the nix-darwin setup that uses
  `home-manager.sharedModules` and `programs/tools/+defaults.nix`.
- Public CLI text is English. German TTS examples are marked as examples, not
  as documentation language.

## Verification

Run before committing:

```console
$ nix develop --command pytest -q
$ nix develop --command ruff check .
$ nix build .#default
```

The test suite must stay hermetic (fake registry + `file://` URLs + mock engine).
Do not add network-dependent tests.

## SEO / discoverability

The README and GitHub repository metadata should remain searchable for:
"local text-to-speech macOS", "offline TTS Apple Silicon", "Voxtral TTS MLX",
"Qwen3-TTS MLX", "Nix flake", "Home Manager module", "Ollama-style TTS",
"German TTS offline", "voice cloning macOS", "MP3 TTS", "streaming TTS". Use
natural prose; do not stuff keywords.

## Git

- Default branch: `main`.
- Conventional, imperative commit subjects in English.
- Do not commit model weights, generated WAVs, virtualenvs or secrets.
- Review before committing; the Manager runs the reviewed commit on the host.
