"""Command line interface for ttspeak."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__, config, paths, store, voices
from .constants import CONFIG_KEYS, EMOTION_INSTRUCTS, normalize_language
from .errors import TtspeakError, UsageError
from .registry import METHOD_LABELS, load_registry, registry_path, resolve_model
from .speak import SpeakOptions, print_result, speak, voice_label
from .util import human_size

COMMANDS = {
    "run",
    "pull",
    "list",
    "search",
    "show",
    "rm",
    "prune",
    "voices",
    "voice",
    "config",
    "runtime",
    "doctor",
    "version",
}

TOP_HELP = """ttspeak — local text-to-speech, Ollama style.

Usage:
  ttspeak "Hallo Welt" [flags]
  ttspeak pull MODEL [--force]
  ttspeak list | search [QUERY] | show MODEL | rm MODEL
  ttspeak prune --keep MODEL [MODEL ...] --yes
  ttspeak voices | voice add|rm|show|prune ...
  ttspeak config get|set|unset|list ...
  ttspeak runtime install|status
  ttspeak doctor
  ttspeak version

Synthesis flags:
  -m, --model ID       model id (default: config / voxtral:4b)
      --voice NAME     preset voice or cloned profile
      --emotion NAME   neutral|happy|sad|angry|excited|calm|serious|whisper
      --instruct TEXT  free-form style instruction
      --language LANG  de|en|fr|es|it|pt|ru|ja|ko|zh or full name
      --speed FLOAT    0.5 .. 2.0
  -o, --output FILE    write a file (wav, mp3, flac, ogg, opus, m4a)
      --play/--no-play play audio (default: on; live streaming without -o)
      --engine ENGINE  mlx (default) or mock (tests/dev)
      --json           machine-readable result

Run 'ttspeak COMMAND --help' for command details.
"""


def _json_print(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))


def _speak_json(result) -> dict[str, Any]:
    return {
        "output": str(result.output) if result.output else None,
        "streamed": result.result.streamed,
        "format": result.format,
        "duration": result.result.duration,
        "sample_rate": result.result.sample_rate,
        "model": result.spec.id,
        "voice": voice_label(result),
        "language": result.language,
        "speed": result.speed,
        "engine": result.engine,
    }


def _add_speak_flags(parser: argparse.ArgumentParser, *, include_model: bool = True) -> None:
    if include_model:
        parser.add_argument("-m", "--model", help="model id, e.g. voxtral:4b")
    parser.add_argument("--voice", help="preset voice or cloned profile name")
    parser.add_argument(
        "--emotion",
        choices=list(EMOTION_INSTRUCTS),
        help="emotion preset mapped to a model style instruction",
    )
    parser.add_argument("--instruct", help="free-form style instruction")
    parser.add_argument(
        "--language",
        help="language code or name (de, en, German, English, ...)",
    )
    parser.add_argument("--speed", type=float, help="speech speed, 0.5 .. 2.0")
    parser.add_argument("-o", "--output", help="output file (wav, mp3, flac, ogg, opus, m4a)")
    play = parser.add_mutually_exclusive_group()
    play.add_argument("--play", dest="play", action="store_true", help="play the audio")
    play.add_argument("--no-play", dest="play", action="store_false", help="do not play")
    parser.set_defaults(play=None)
    parser.add_argument("--engine", choices=["mlx", "mock"], help="speech backend")
    parser.add_argument("--json", action="store_true", help="print a JSON result")


def _speak_options(args: argparse.Namespace, *, text: str, model: str | None, explicit: bool) -> SpeakOptions:
    return SpeakOptions(
        text=text,
        model=model,
        model_explicit=explicit,
        voice=args.voice,
        language=args.language,
        speed=args.speed,
        emotion=args.emotion,
        instruct=args.instruct,
        play=args.play,
        output=args.output,
        engine=args.engine,
    )


def _cmd_speak(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak", description="Generate speech from text.")
    parser.add_argument("text", nargs="+", help="text to speak")
    _add_speak_flags(parser)
    args = parser.parse_args(argv)
    text = " ".join(args.text).strip()
    result = speak(_speak_options(args, text=text, model=args.model, explicit=args.model is not None))
    if args.json:
        _json_print(_speak_json(result))
    else:
        print_result(result)
    return 0


def _cmd_run(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak run", description="Generate speech with an explicit model.")
    parser.add_argument("model", help="model id, e.g. voxtral:4b")
    parser.add_argument("text", nargs="+", help="text to speak")
    _add_speak_flags(parser, include_model=False)
    args = parser.parse_args(argv)
    text = " ".join(args.text).strip()
    result = speak(_speak_options(args, text=text, model=args.model, explicit=True))
    if args.json:
        _json_print(_speak_json(result))
    else:
        print_result(result)
    return 0


def _cmd_pull(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak pull", description="Download model weights.")
    parser.add_argument("model", help="model id from the registry")
    parser.add_argument("--force", action="store_true", help="replace an installed copy")
    parser.add_argument("--revision", help="Hugging Face revision (branch, tag or sha)")
    args = parser.parse_args(argv)

    spec = resolve_model(args.model)
    already = store.is_installed(spec.id)
    installed = store.pull_model(
        spec.id,
        force=args.force,
        revision=args.revision,
        progress=store.PullProgress(),
    )
    if already and not args.force:
        print(f"{installed.spec.id} is already installed at {installed.path}")
    else:
        print(f"Pulled {installed.spec.id} ({human_size(installed.size_bytes)}) to {installed.path}")
    return 0


def _default_model_id() -> str | None:
    try:
        value = config.load_effective().get("model")
        return resolve_model(str(value)).id if value else None
    except TtspeakError:
        return None


def _cmd_list(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak list", description="List installed models.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    installed = store.list_installed()
    default = _default_model_id()
    rows = [
        {
            "id": item.spec.id,
            "size_bytes": item.size_bytes,
            "installed_at": item.installed_at,
            "method": item.spec.method,
            "path": str(item.path),
            "default": item.spec.id == default,
        }
        for item in installed
    ]
    if args.json:
        _json_print(rows)
        return 0
    if not rows:
        print("No models installed. Run: ttspeak pull voxtral:4b")
        return 0
    print(f"{'ID':<20} {'SIZE':>10}  {'INSTALLED':<10}  METHOD")
    for row in rows:
        marker = "*" if row["default"] else " "
        print(
            f"{marker} {row['id']:<18} {human_size(row['size_bytes']):>10}  "
            f"{row['installed_at'][:10]:<10}  {row['method']}"
        )
    print("\n* default model")
    return 0


def _cmd_search(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak search", description="Search the model registry.")
    parser.add_argument("query", nargs="?", default="", help="filter text")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    models = load_registry()
    query = args.query.lower()
    rows = []
    for spec in models.values():
        haystack = f"{spec.id} {spec.repo} {spec.description}".lower()
        if query and query not in haystack:
            continue
        rows.append(
            {
                "id": spec.id,
                "repo": spec.repo,
                "method": spec.method,
                "description": spec.description,
                "size_bytes": spec.size_hint,
                "installed": store.is_installed(spec.id),
            }
        )
    rows.sort(key=lambda item: item["id"])
    if args.json:
        _json_print(rows)
        return 0
    if not rows:
        print(f"No models match '{args.query}'.")
        return 0
    for row in rows:
        marker = "*" if row["installed"] else " "
        size = human_size(row["size_bytes"]) if row["size_bytes"] else "?"
        print(f"{marker} {row['id']:<20} {size:>9}  {row['method']}")
        if row["description"]:
            print(f"    {row['description']}")
    print("\n* installed. Pull with: ttspeak pull MODEL")
    return 0


def _cmd_show(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak show", description="Show model details.")
    parser.add_argument("model")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    spec = resolve_model(args.model)
    installed = store.get_installed(spec.id)
    data = {
        "id": spec.id,
        "repo": spec.repo,
        "method": spec.method,
        "method_label": METHOD_LABELS.get(spec.method, spec.method),
        "description": spec.description,
        "voices": list(spec.voices),
        "default_voice": spec.default_voice,
        "languages": list(spec.languages),
        "size_hint": spec.size_hint,
        "installed": installed is not None,
        "path": str(installed.path) if installed else None,
        "size_bytes": installed.size_bytes if installed else None,
        "revision": installed.revision if installed else None,
        "installed_at": installed.installed_at if installed else None,
    }
    if args.json:
        _json_print(data)
        return 0
    print(f"ID:          {data['id']}")
    print(f"Repo:        {data['repo']}")
    print(f"Method:      {data['method_label']}")
    print(f"Languages:   {', '.join(data['languages']) or '-'}")
    print(f"Voices:      {', '.join(data['voices']) or '-'}")
    print(f"Default:     {data['default_voice'] or '-'}")
    if installed:
        print(f"Installed:   yes ({human_size(installed.size_bytes)}, revision {installed.revision})")
        print(f"Path:        {installed.path}")
    else:
        hint = f" (~{human_size(spec.size_hint)})" if spec.size_hint else ""
        print(f"Installed:   no{hint}")
        print(f"Install:     ttspeak pull {spec.id}")
    return 0


def _cmd_rm(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak rm", description="Remove model weights.")
    parser.add_argument("model")
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask")
    args = parser.parse_args(argv)

    spec = store.resolve_installed_or_registry(args.model)
    profiles = voices.profiles_for_model(spec.id)
    if profiles:
        names = ", ".join(profile.name for profile in profiles)
        print(
            f"warning: voice profile(s) {names} use {spec.id}; they will stop working.",
            file=sys.stderr,
        )
    path = store.remove_model(spec.id, assume_yes=args.yes)
    print(f"Removed {spec.id} ({path})")
    return 0


def _cmd_prune(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak prune", description="Remove models not in a keep list.")
    parser.add_argument("--keep", nargs="+", default=[], metavar="MODEL", help="models to keep")
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask")
    args = parser.parse_args(argv)

    keep = []
    for item in args.keep:
        keep.extend(part for part in item.split(",") if part)
    removed = store.prune_models(keep, assume_yes=args.yes)
    if not removed:
        print("Nothing to prune.")
    else:
        print(f"Removed: {', '.join(removed)}")
    return 0


def _cmd_voices(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak voices", description="List preset and cloned voices.")
    parser.add_argument("-m", "--model", help="show preset voices for this model")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    model_id = args.model or _default_model_id()
    if model_id is None:
        registry = load_registry()
        model_id = next(iter(registry), None)
    if model_id is None:
        raise UsageError("No models in the registry.")
    spec = resolve_model(model_id)
    profiles = voices.list_profiles()
    data = {
        "model": spec.id,
        "presets": list(spec.voices),
        "profiles": [
            {
                "name": profile.name,
                "model": profile.model,
                "path": str(profile.path),
                "created_at": profile.created_at,
            }
            for profile in profiles
        ],
    }
    if args.json:
        _json_print(data)
        return 0
    print(f"Preset voices for {spec.id}:")
    if spec.voices:
        for name in spec.voices:
            default = " (default)" if name == spec.default_voice else ""
            print(f"  {name}{default}")
    else:
        print("  none (this model uses cloning or voice design)")
    print("\nCloned profiles:")
    if profiles:
        for profile in profiles:
            print(f"  {profile.name:<20} -> {profile.model}  {profile.path}")
    else:
        print("  none. Create one with: ttspeak voice add NAME --audio ref.wav --text \"...\"")
    return 0


def _cmd_voice(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak voice", description="Manage cloned voice profiles.")
    sub = parser.add_subparsers(dest="voice_command", required=True)

    add = sub.add_parser("add", help="create a cloned voice profile")
    add.add_argument("name")
    add.add_argument("--audio", required=True, help="reference WAV recording")
    add.add_argument("--text", required=True, help="exact transcript of the reference audio")
    add.add_argument("--model", default="qwen3:0.6b-base", help="Base model used for cloning")
    add.add_argument("--force", action="store_true", help="replace an existing profile")

    rm = sub.add_parser("rm", help="remove a voice profile")
    rm.add_argument("name")
    rm.add_argument("-y", "--yes", action="store_true")

    show = sub.add_parser("show", help="show a voice profile")
    show.add_argument("name")
    show.add_argument("--json", action="store_true")

    prune = sub.add_parser("prune", help="remove profiles not in a keep list")
    prune.add_argument("--keep", nargs="+", default=[], metavar="NAME")
    prune.add_argument("-y", "--yes", action="store_true")

    args = parser.parse_args(argv)
    if args.voice_command == "add":
        profile = voices.add_profile(
            args.name,
            Path(args.audio),
            args.text,
            model=args.model,
            force=args.force,
        )
        print(f"Added voice '{profile.name}' using {profile.model} at {profile.path}")
        return 0
    if args.voice_command == "rm":
        profile = voices.remove_profile(args.name, assume_yes=args.yes)
        print(f"Removed voice '{profile.name}' ({profile.path})")
        return 0
    if args.voice_command == "prune":
        keep = []
        for item in args.keep:
            keep.extend(part for part in item.split(",") if part)
        removed = voices.prune_profiles(keep, assume_yes=args.yes)
        if not removed:
            print("Nothing to prune.")
        else:
            print(f"Removed voices: {', '.join(removed)}")
        return 0

    profile = voices.get_profile(args.name)
    if profile is None:
        raise UsageError(f"Voice profile '{args.name}' does not exist.")
    data = profile.to_dict()
    data["path"] = str(profile.path)
    data["audio"] = str(profile.audio)
    if args.json:
        _json_print(data)
    else:
        print(f"Name:      {profile.name}")
        print(f"Model:     {profile.model}")
        print(f"Audio:     {profile.audio}")
        print(f"SHA-256:   {profile.sha256}")
        print(f"Created:   {profile.created_at}")
        print(f"Transcript: {profile.ref_text}")
    return 0


def _config_sources() -> dict[str, str]:
    declarative = config.load_declarative_defaults()
    user = config.load_user_config()
    env_keys = set(config.env_overrides())
    sources: dict[str, str] = {}
    for key in CONFIG_KEYS:
        if key in env_keys:
            sources[key] = "env"
        elif key in user:
            sources[key] = "user"
        elif key in declarative:
            sources[key] = "declarative"
        else:
            sources[key] = "built-in"
    return sources


def _cmd_config(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak config", description="Read or change user configuration.")
    sub = parser.add_subparsers(dest="config_command", required=True)

    get = sub.add_parser("get", help="print one effective value")
    get.add_argument("key", choices=CONFIG_KEYS)
    get.add_argument("--user", action="store_true", help="only the mutable user value")
    get.add_argument("--json", action="store_true")

    set_parser = sub.add_parser("set", help="set a user value")
    set_parser.add_argument("key", choices=CONFIG_KEYS)
    set_parser.add_argument("value")

    unset = sub.add_parser("unset", help="remove a user value")
    unset.add_argument("key", choices=CONFIG_KEYS)

    listing = sub.add_parser("list", help="show effective values and their source")
    listing.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.config_command == "get":
        value = config.get_user_value(args.key) if args.user else config.load_effective().get(args.key)
        if args.json:
            _json_print({"key": args.key, "value": value})
        elif value is not None:
            print(config.render_value(value))
        return 0 if value is not None else 1

    if args.config_command == "set":
        value = args.value
        if args.key == "model":
            value = resolve_model(value).id
        elif args.key == "language":
            value = normalize_language(value)
        saved = config.set_user_value(args.key, value)
        print(f"{args.key} = {config.render_value(saved)}")
        return 0

    if args.config_command == "unset":
        existed = config.unset_user_value(args.key)
        print(f"Unset {args.key}." if existed else f"{args.key} was not set.")
        return 0

    effective = config.load_effective()
    sources = _config_sources()
    if args.json:
        _json_print(
            {
                key: {"value": effective.get(key), "source": sources[key]}
                for key in CONFIG_KEYS
            }
        )
        return 0
    print(f"{'KEY':<10} {'VALUE':<24} SOURCE")
    for key in CONFIG_KEYS:
        print(f"{key:<10} {config.render_value(effective.get(key)) or '-':<24} {sources[key]}")
    return 0


def _cmd_runtime(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak runtime", description="Manage the isolated MLX runtime.")
    sub = parser.add_subparsers(dest="runtime_command", required=True)
    install = sub.add_parser("install", help="create the runtime venv and install mlx-audio")
    install.add_argument("--python", help="host Python interpreter used to create the venv")
    install.add_argument("--version", help="pin an mlx-audio version")
    install.add_argument("--force", action="store_true", help="recreate the venv")
    sub.add_parser("status", help="show runtime health")

    args = parser.parse_args(argv)
    if args.runtime_command == "install":
        from .engines.mlx import install_runtime

        status = install_runtime(
            python=Path(args.python).expanduser() if args.python else None,
            version=args.version,
            force=args.force,
        )
        print(f"Runtime ready: {status.python} ({status.detail})")
        return 0

    from .engines.mlx import runtime_status

    status = runtime_status()
    print(f"Managed runtime: {paths.runtime_python()}")
    print(f"Active Python:   {status.python or '-'}")
    print(f"Status:          {'ok' if status.healthy else 'not available'}")
    print(f"Detail:          {status.detail}")
    if not status.healthy:
        print("Install with:    ttspeak runtime install")
        return 1
    return 0


def _cmd_doctor(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="ttspeak doctor", description="Check the local setup.")
    parser.parse_args(argv)

    failures = 0
    print(f"ttspeak {__version__}")
    platform_ok = sys.platform == "darwin" and os.uname().machine in {"arm64", "aarch64"}
    print(f"Platform:      {sys.platform} {os.uname().machine} {'(mlx capable)' if platform_ok else '(mock only)'}")
    print(f"Data root:     {paths.home()}")
    try:
        paths.ensure_runtime_dirs()
        print("Data root:     writable")
    except OSError as exc:
        print(f"Data root:     NOT writable: {exc}")
        failures += 1

    try:
        registry = load_registry()
        print(f"Registry:      {registry_path()} ({len(registry)} models)")
    except TtspeakError as exc:
        print(f"Registry:      ERROR: {exc}")
        failures += 1

    from .engines.mlx import runtime_status

    status = runtime_status()
    if status.healthy:
        print(f"MLX runtime:   {status.detail}")
    else:
        print(f"MLX runtime:   not available ({status.detail})")
        print("               install with: ttspeak runtime install")
        failures += 1

    default = _default_model_id()
    if default is None:
        print("Default model: invalid or unset")
        failures += 1
    elif store.is_installed(default):
        print(f"Default model: {default} (installed)")
    else:
        print(f"Default model: {default} (not installed: ttspeak pull {default})")
        failures += 1

    profiles = voices.list_profiles()
    print(f"Voice profiles: {len(profiles)}")
    for profile in profiles:
        marker = "ok" if store.is_installed(profile.model) else "missing model"
        print(f"  {profile.name:<20} {profile.model} ({marker})")
    return 1 if failures else 0


def _dispatch(argv: Sequence[str]) -> int:
    if not argv:
        print(TOP_HELP, end="")
        return 0
    head = argv[0]
    if head in {"-h", "--help", "help"}:
        print(TOP_HELP, end="")
        return 0
    if head in {"--version", "-V"}:
        print(f"ttspeak {__version__}")
        return 0
    if head == "version":
        print(f"ttspeak {__version__}")
        return 0

    rest = list(argv[1:])
    if head == "speak":
        return _cmd_speak(rest)
    if head == "run":
        return _cmd_run(rest)
    if head == "pull":
        return _cmd_pull(rest)
    if head == "list":
        return _cmd_list(rest)
    if head == "search":
        return _cmd_search(rest)
    if head == "show":
        return _cmd_show(rest)
    if head == "rm":
        return _cmd_rm(rest)
    if head == "prune":
        return _cmd_prune(rest)
    if head == "voices":
        return _cmd_voices(rest)
    if head == "voice":
        return _cmd_voice(rest)
    if head == "config":
        return _cmd_config(rest)
    if head == "runtime":
        return _cmd_runtime(rest)
    if head == "doctor":
        return _cmd_doctor(rest)

    # No known command: treat the whole argv as text + synthesis flags.
    return _cmd_speak(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        return _dispatch(arguments)
    except TtspeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130
