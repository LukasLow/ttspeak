"""Generate a local voice tournament and a Tailwind HTML player.

This is a development helper, not part of the installed CLI. It uses the
ttspeak Python API with the MLX engine and writes MP3 files plus an HTML page
that can be opened in a browser.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tournament"
AUDIO = OUT / "audio"
MANIFEST = OUT / "manifest.json"
LOG = OUT / "generation.log"

os.environ.setdefault("TTSPEAK_HOME", "/tmp/ttspeak-live")

from ttspeak.speak import SpeakOptions, speak

LANGUAGES = {
    "de": {
        "label": "Deutsch",
        "text": (
            "Guten Abend. Heute prüfen wir, wie natürlich diese Stimme klingt. "
            "Bitte achte auf Aussprache, Rhythmus und Melodie."
        ),
    },
    "en": {
        "label": "English",
        "text": (
            "Good evening. Today we are checking how natural this voice sounds. "
            "Listen for pronunciation, rhythm, and melody."
        ),
    },
    "ru": {
        "label": "Русский",
        "text": (
            "Добрый вечер. Сегодня мы проверяем, насколько естественно звучит этот голос. "
            "Обрати внимание на произношение, ритм и интонацию."
        ),
    },
}

QWEN_VOICES = [
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
]
VOXTRAL_VOICES = [
    "de_female",
    "de_male",
    "casual_female",
    "casual_male",
    "cheerful_female",
    "neutral_female",
    "neutral_male",
    "fr_female",
    "fr_male",
    "es_female",
    "es_male",
    "it_female",
    "it_male",
    "pt_female",
    "pt_male",
    "nl_female",
    "nl_male",
    "ar_male",
    "hi_female",
    "hi_male",
]

MODELS = [
    {
        "id": "qwen3:0.6b",
        "slug": "qwen3-0.6b",
        "label": "Qwen3-TTS 0.6B CustomVoice 8-bit",
        "family": "qwen",
        "voices": QWEN_VOICES,
        "languages": ["de", "en", "ru"],
    },
    {
        "id": "qwen3:1.7b",
        "slug": "qwen3-1.7b",
        "label": "Qwen3-TTS 1.7B CustomVoice 8-bit",
        "family": "qwen",
        "voices": QWEN_VOICES,
        "languages": ["de", "en", "ru"],
    },
    {
        "id": "voxtral:4b",
        "slug": "voxtral-4b",
        "label": "Voxtral 4B TTS 4-bit",
        "family": "voxtral",
        "voices": VOXTRAL_VOICES,
        # Voxtral TTS has no Russian voice support.
        "languages": ["de", "en"],
    },
]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")


def audio_path(lang: str, model: dict, voice: str) -> Path:
    return AUDIO / lang / model["slug"] / f"{slug(voice)}.mp3"


def ffprobe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0.0


def load_manifest() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {item["key"]: item for item in data.get("samples", [])}


def save_manifest(samples: list[dict]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "generated_at": samples[-1].get("generated_at") if samples else None,
                "samples": samples,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def generate(args: argparse.Namespace) -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not args.verbose:
        log_handle = LOG.open("a", buffering=1)
        os.dup2(log_handle.fileno(), 2)

    previous = load_manifest()
    samples = list(previous.values())
    by_key = {item["key"]: item for item in samples}

    plan: list[tuple[str, dict, str]] = []
    for lang in LANGUAGES:
        if args.language and lang != args.language:
            continue
        for model in MODELS:
            if args.model and model["id"] != args.model:
                continue
            if lang not in model["languages"]:
                continue
            for voice in model["voices"]:
                if args.voice and voice != args.voice:
                    continue
                plan.append((lang, model, voice))

    if args.list:
        for lang, model, voice in plan:
            print(f"{lang:2}  {model['id']:<16}  {voice}")
        print(f"{len(plan)} samples")
        return

    print(f"Generating {len(plan)} samples into {OUT}")
    for index, (lang, model, voice) in enumerate(plan, start=1):
        path = audio_path(lang, model, voice)
        key = f"{lang}/{model['slug']}/{slug(voice)}"
        if path.exists() and path.stat().st_size > 0 and key in by_key and not args.force:
            print(f"[{index}/{len(plan)}] skip {key}")
            continue
        print(f"[{index}/{len(plan)}] {key}", flush=True)
        try:
            result = speak(
                SpeakOptions(
                    text=LANGUAGES[lang]["text"],
                    model=model["id"],
                    model_explicit=True,
                    voice=voice,
                    language=lang,
                    play=False,
                    output=str(path),
                    engine="mlx",
                )
            )
            entry = {
                "key": key,
                "language": lang,
                "language_label": LANGUAGES[lang]["label"],
                "text": LANGUAGES[lang]["text"],
                "model": model["id"],
                "model_label": model["label"],
                "model_slug": model["slug"],
                "family": model["family"],
                "voice": voice,
                "file": path.relative_to(OUT).as_posix(),
                "duration": round(result.result.duration, 3),
                "size": path.stat().st_size,
            }
        except Exception as exc:  # noqa: BLE001 - keep the tournament going
            traceback.print_exc()
            print(f"  ERROR: {type(exc).__name__}: {exc}", flush=True)
            entry = {
                "key": key,
                "language": lang,
                "language_label": LANGUAGES[lang]["label"],
                "text": LANGUAGES[lang]["text"],
                "model": model["id"],
                "model_label": model["label"],
                "model_slug": model["slug"],
                "family": model["family"],
                "voice": voice,
                "file": path.relative_to(OUT).as_posix(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        by_key[key] = entry
        samples = list(by_key.values())
        save_manifest(samples)

    save_manifest(samples)
    print(f"Manifest: {MANIFEST}")


def make_html() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    samples = [item for item in data["samples"] if "error" not in item]
    samples.sort(
        key=lambda item: (
            list(LANGUAGES).index(item["language"]),
            item["family"],
            item["model"],
            item["voice"],
        )
    )
    by_lang: dict[str, list[dict]] = {lang: [] for lang in LANGUAGES}
    for item in samples:
        by_lang[item["language"]].append(item)

    cards = []
    for lang, items in by_lang.items():
        lang_data = LANGUAGES[lang]
        rows = []
        for item in items:
            duration = item.get("duration") or 0
            rows.append(
                f"""
                <article class="sample rounded-2xl border border-slate-700 bg-slate-900/70 p-4 shadow-lg"
                         data-lang="{lang}" data-family="{item['family']}" data-model="{html.escape(item['model_slug'])}">
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <h4 class="font-semibold text-slate-100">{html.escape(item['voice'])}</h4>
                      <p class="text-xs text-slate-400">{html.escape(item['model_label'])}</p>
                    </div>
                    <span class="shrink-0 rounded-full bg-slate-800 px-2 py-1 text-xs text-slate-300">{duration:.2f}s</span>
                  </div>
                  <audio class="mt-3 w-full" controls preload="none" src="{html.escape(item['file'])}"></audio>
                </article>
                """
            )
        cards.append(
            f"""
            <section class="lang-section" data-lang="{lang}">
              <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 class="text-2xl font-bold text-white">{html.escape(lang_data['label'])} <span class="text-sm font-normal text-slate-400">({len(items)} voices)</span></h2>
                  <p class="mt-1 max-w-4xl text-sm leading-relaxed text-slate-300">{html.escape(lang_data['text'])}</p>
                </div>
              </div>
              <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {''.join(rows)}
              </div>
            </section>
            """
        )

    notes = ""
    if "ru" in by_lang and not any(item["family"] == "voxtral" for item in by_lang["ru"]):
        notes = (
            '<p class="mt-4 rounded-xl border border-amber-700/60 bg-amber-950/40 p-4 text-sm text-amber-200">'
            "Voxtral TTS does not support Russian. Russian is therefore Qwen3-TTS only."
            "</p>"
        )

    html_text = f"""<!doctype html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ttspeak voice tournament</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100 antialiased">
  <main class="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
    <header class="mb-8">
      <p class="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">ttspeak · local TTS</p>
      <h1 class="mt-2 text-4xl font-black tracking-tight text-white">Voice tournament</h1>
      <p class="mt-3 max-w-4xl text-slate-300">
        German, English and Russian. Qwen3-TTS 0.6B/1.7B CustomVoice and Voxtral 4B.
        Every preset voice was synthesized with the same text per language.
      </p>
      <div class="mt-5 flex flex-wrap gap-2">
        <button class="filter rounded-full bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950" data-filter="all">All</button>
        <button class="filter rounded-full bg-slate-800 px-4 py-2 text-sm" data-filter="de">Deutsch</button>
        <button class="filter rounded-full bg-slate-800 px-4 py-2 text-sm" data-filter="en">English</button>
        <button class="filter rounded-full bg-slate-800 px-4 py-2 text-sm" data-filter="ru">Русский</button>
        <span class="mx-2 h-8 w-px bg-slate-700"></span>
        <button class="filter rounded-full bg-slate-800 px-4 py-2 text-sm" data-filter="qwen">Qwen</button>
        <button class="filter rounded-full bg-slate-800 px-4 py-2 text-sm" data-filter="voxtral">Voxtral</button>
        <button id="stop-all" class="ml-auto rounded-full border border-rose-500/50 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10">Stop all</button>
      </div>
      {notes}
    </header>
    <div class="space-y-12">
      {''.join(cards)}
    </div>
  </main>
  <script>
    const buttons = [...document.querySelectorAll('.filter')];
    const samples = [...document.querySelectorAll('.sample')];
    let active = 'all';
    function applyFilter() {{
      for (const card of samples) {{
        const lang = card.dataset.lang;
        const family = card.dataset.family;
        const show = active === 'all' || active === lang || active === family;
        card.classList.toggle('hidden', !show);
      }}
      for (const section of document.querySelectorAll('.lang-section')) {{
        const visible = [...section.querySelectorAll('.sample')].some((card) => !card.classList.contains('hidden'));
        section.classList.toggle('hidden', !visible);
      }}
      for (const button of buttons) {{
        const selected = button.dataset.filter === active;
        button.classList.toggle('bg-cyan-500', selected);
        button.classList.toggle('text-slate-950', selected);
        button.classList.toggle('bg-slate-800', !selected);
      }}
    }}
    for (const button of buttons) {{
      button.addEventListener('click', () => {{
        active = button.dataset.filter;
        applyFilter();
      }});
    }}
    document.getElementById('stop-all').addEventListener('click', () => {{
      for (const audio of document.querySelectorAll('audio')) {{
        audio.pause();
        audio.currentTime = 0;
      }}
    }});
    applyFilter();
  </script>
</body>
</html>
"""
    (OUT / "index.html").write_text(html_text, encoding="utf-8")
    print(f"HTML: {OUT / 'index.html'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=list(LANGUAGES))
    parser.add_argument("--model")
    parser.add_argument("--voice")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.html_only:
        make_html()
        return
    generate(args)
    if not args.list:
        make_html()


if __name__ == "__main__":
    main()
