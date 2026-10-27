"""Build a blind A/B tournament page from tournament/manifest.json (dev helper)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOURNAMENT = ROOT / "tournament"
MANIFEST = TOURNAMENT / "manifest.json"
TARGET = TOURNAMENT / "blind.html"

QWEN_GENDER = {
    "Vivian": "female",
    "Serena": "female",
    "Uncle_Fu": "male",
    "Dylan": "male",
    "Eric": "male",
    "Ryan": "male",
    "Aiden": "male",
    "Ono_Anna": "female",
    "Sohee": "female",
}


def sample_gender(sample: dict) -> str:
    if sample["family"] == "voxtral":
        return "male" if sample["voice"].endswith("_male") else "female"
    return QWEN_GENDER[sample["voice"]]


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    samples = {
        item["key"]: item for item in manifest["samples"] if "error" not in item
    }
    languages = {
        item["language"]: {
            "label": item["language_label"],
            "text": item["text"],
        }
        for item in samples.values()
    }
    brackets = []
    for lang in ("de", "en", "ru"):
        for gender in ("female", "male"):
            candidates = [
                key
                for key, item in samples.items()
                if item["language"] == lang and sample_gender(item) == gender
            ]
            if not candidates:
                continue
            brackets.append(
                {
                    "id": f"{lang}-{gender}",
                    "lang": lang,
                    "gender": gender,
                    "label": f"{languages[lang]['label']} · {gender}",
                    "candidates": candidates,
                }
            )

    data = {
        "languages": languages,
        "brackets": brackets,
        "samples": {
            key: {
                "key": key,
                "voice": item["voice"],
                "model": item["model"],
                "model_label": item["model_label"],
                "family": item["family"],
                "file": item["file"],
                "duration": item.get("duration", 0),
            }
            for key, item in samples.items()
        },
    }
    payload = json.dumps(data, ensure_ascii=False)

    html_text = HTML.replace("__DATA__", payload)
    TARGET.write_text(html_text, encoding="utf-8")
    print(f"Wrote {TARGET} with {len(brackets)} brackets")
    for bracket in brackets:
        print(f"  {bracket['label']}: {len(bracket['candidates'])} candidates")


HTML = """<!doctype html>
<html lang="en" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ttspeak · blind voice tournament</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100 antialiased">
  <main class="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
    <header class="mb-8">
      <p class="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">ttspeak · blind test</p>
      <h1 class="mt-2 text-4xl font-black tracking-tight text-white">Six brackets. Two voices. One winner.</h1>
      <p class="mt-3 max-w-3xl text-slate-300">
        Every matchup is blind: only A and B are shown. Pick the voice you prefer for the
        language and gender. Names and models are revealed only when a bracket is complete.
        At the end, copy the result text and send it back.
      </p>
      <p class="mt-3 rounded-xl border border-amber-700/60 bg-amber-950/40 p-4 text-sm text-amber-200">
        Voxtral TTS has no Russian support. The Russian brackets are Qwen3-TTS only.
      </p>
      <div class="mt-5 flex flex-wrap gap-2">
        <button id="reset-all" class="rounded-full border border-rose-500/50 px-4 py-2 text-sm text-rose-300 hover:bg-rose-500/10">Reset all brackets</button>
        <a href="index.html" class="rounded-full border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">All voice samples</a>
      </div>
    </header>

    <section id="brackets" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"></section>

    <section id="active" class="mt-10 hidden"></section>

    <section class="mt-12">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-2xl font-bold text-white">Results</h2>
          <p class="mt-1 text-sm text-slate-400">Complete all six brackets, then copy this text and send it to me.</p>
        </div>
        <button id="copy-results" class="rounded-full bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400">Copy results</button>
      </div>
      <textarea id="results" readonly class="mt-4 h-64 w-full rounded-2xl border border-slate-700 bg-slate-900 p-4 font-mono text-sm text-slate-200"></textarea>
      <p id="copy-status" class="mt-2 text-sm text-emerald-400"></p>
    </section>
  </main>

  <script>
    const DATA = __DATA__;
    const STORAGE_KEY = 'ttspeak-blind-v1';
    const state = loadState();

    function loadState() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) return JSON.parse(raw);
      } catch (error) {
        console.warn(error);
      }
      return { active: null, brackets: {} };
    }

    function saveState() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }

    function shuffle(items) {
      const copy = [...items];
      for (let i = copy.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      return copy;
    }

    function bracketState(id) {
      if (!state.brackets[id]) {
        const bracket = DATA.brackets.find((item) => item.id === id);
        state.brackets[id] = {
          remaining: shuffle(bracket.candidates),
          winners: [],
          matchIndex: 0,
          round: 1,
          winner: bracket.candidates.length === 1 ? bracket.candidates[0] : null,
          history: [],
        };
      }
      const bracket = state.brackets[id];
      if (!bracket.winner && bracket.remaining.length === 1) {
        bracket.winner = bracket.remaining[0];
      }
      return bracket;
    }

    function currentMatch(bracket) {
      if (bracket.winner) return null;
      const total = Math.floor(bracket.remaining.length / 2);
      if (bracket.matchIndex >= total) return null;
      return [
        bracket.remaining[bracket.matchIndex * 2],
        bracket.remaining[bracket.matchIndex * 2 + 1],
      ];
    }

    function choose(winnerKey) {
      if (!state.active) return;
      const bracket = bracketState(state.active);
      const match = currentMatch(bracket);
      if (!match) return;
      const [a, b] = match;
      if (winnerKey !== a && winnerKey !== b) return;

      bracket.winners.push(winnerKey);
      bracket.history.push({ a, b, winner: winnerKey });
      bracket.matchIndex += 1;

      const matchesInRound = Math.floor(bracket.remaining.length / 2);
      if (bracket.matchIndex >= matchesInRound) {
        if (bracket.remaining.length % 2 === 1) {
          bracket.winners.push(bracket.remaining[bracket.remaining.length - 1]);
        }
        if (bracket.winners.length === 1) {
          bracket.winner = bracket.winners[0];
        } else {
          bracket.remaining = shuffle(bracket.winners);
          bracket.winners = [];
          bracket.matchIndex = 0;
          bracket.round += 1;
        }
      }
      saveState();
      render();
    }

    function startBracket(id) {
      const bracket = bracketState(id);
      if (bracket.winner) {
        resetBracket(id);
      }
      state.active = id;
      saveState();
      render();
    }

    function resetBracket(id) {
      delete state.brackets[id];
      if (state.active === id) state.active = null;
      saveState();
      render();
    }

    function renderBrackets() {
      const root = document.getElementById('brackets');
      root.innerHTML = DATA.brackets.map((bracket) => {
        const b = bracketState(bracket.id);
        const done = Boolean(b.winner);
        const total = bracket.candidates.length;
        const remaining = done ? 1 : b.remaining.length;
        const winner = done ? DATA.samples[b.winner] : null;
        return `
          <article class="rounded-2xl border ${done ? 'border-emerald-600/60' : 'border-slate-700'} bg-slate-900/70 p-5 shadow-lg">
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-400">${escapeHtml(bracket.lang)} · ${bracket.gender}</p>
            <h3 class="mt-1 text-lg font-semibold text-white">${escapeHtml(bracket.label)}</h3>
            <p class="mt-2 text-sm text-slate-400">${done ? 'Winner selected' : `Round ${b.round} · ${remaining} of ${total} remaining`}</p>
            ${winner ? `<p class="mt-3 rounded-xl bg-emerald-950/50 p-3 text-sm text-emerald-200">${escapeHtml(winner.voice)} — ${escapeHtml(winner.model)}</p>` : ''}
            <div class="mt-4 flex flex-wrap gap-2">
              <button data-start="${bracket.id}" class="rounded-full bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400">${done ? 'Restart' : b.matchIndex > 0 ? 'Continue' : 'Start'}</button>
              <button data-reset="${bracket.id}" class="rounded-full border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">Reset</button>
            </div>
          </article>
        `;
      }).join('');
      for (const button of root.querySelectorAll('[data-start]')) {
        button.addEventListener('click', () => startBracket(button.dataset.start));
      }
      for (const button of root.querySelectorAll('[data-reset]')) {
        button.addEventListener('click', () => resetBracket(button.dataset.reset));
      }
    }

    function renderActive() {
      const root = document.getElementById('active');
      if (!state.active) {
        root.classList.add('hidden');
        root.innerHTML = '';
        return;
      }
      const bracket = bracketState(state.active);
      const definition = DATA.brackets.find((item) => item.id === state.active);
      root.classList.remove('hidden');

      if (bracket.winner) {
        const winner = DATA.samples[bracket.winner];
        root.innerHTML = `
          <div class="rounded-3xl border border-emerald-600/60 bg-emerald-950/30 p-8 text-center">
            <p class="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-300">${escapeHtml(definition.label)} · complete</p>
            <h2 class="mt-3 text-3xl font-black text-white">${escapeHtml(winner.voice)}</h2>
            <p class="mt-1 text-slate-300">${escapeHtml(winner.model_label)}</p>
            <p class="mt-1 text-sm text-slate-400">${winner.duration.toFixed(2)}s</p>
            <div class="mt-6 flex justify-center gap-2">
              <button id="back-brackets" class="rounded-full bg-cyan-500 px-5 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400">Back to brackets</button>
              <button id="restart-active" class="rounded-full border border-slate-700 px-5 py-2 text-sm text-slate-300 hover:bg-slate-800">Restart bracket</button>
            </div>
          </div>
        `;
        document.getElementById('back-brackets').addEventListener('click', () => {
          state.active = null;
          saveState();
          render();
        });
        document.getElementById('restart-active').addEventListener('click', () => resetBracket(state.active));
        return;
      }

      const match = currentMatch(bracket);
      if (!match) {
        root.innerHTML = `<p class="text-slate-300">This bracket has no match. Reset it.</p>`;
        return;
      }
      const sampleA = DATA.samples[match[0]];
      const sampleB = DATA.samples[match[1]];
      const matchesInRound = Math.floor(bracket.remaining.length / 2);
      root.innerHTML = `
        <div class="rounded-3xl border border-slate-700 bg-slate-900/80 p-6 shadow-2xl">
          <div class="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p class="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">${escapeHtml(definition.label)}</p>
              <h2 class="mt-1 text-2xl font-bold text-white">Round ${bracket.round} · Match ${bracket.matchIndex + 1} of ${matchesInRound}</h2>
              <p class="mt-1 text-sm text-slate-400">${escapeHtml(DATA.languages[definition.lang].text)}</p>
            </div>
            <button id="close-active" class="rounded-full border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">Close</button>
          </div>
          <div class="mt-6 grid gap-4 md:grid-cols-2">
            ${audioCard('A', sampleA)}
            ${audioCard('B', sampleB)}
          </div>
          <div class="mt-6 grid gap-3 sm:grid-cols-2">
            <button data-choice="${match[0]}" class="rounded-2xl bg-cyan-500 px-5 py-4 text-lg font-bold text-slate-950 hover:bg-cyan-400">A sounds better</button>
            <button data-choice="${match[1]}" class="rounded-2xl bg-cyan-500 px-5 py-4 text-lg font-bold text-slate-950 hover:bg-cyan-400">B sounds better</button>
          </div>
          <p class="mt-3 text-center text-xs text-slate-500">Keyboard: A or B. Names stay hidden until this bracket is complete.</p>
        </div>
      `;
      document.getElementById('close-active').addEventListener('click', () => {
        state.active = null;
        saveState();
        render();
      });
      for (const button of root.querySelectorAll('[data-choice]')) {
        button.addEventListener('click', () => choose(button.dataset.choice));
      }
      const audioA = document.getElementById('audio-a');
      const audioB = document.getElementById('audio-b');
      if (audioA && audioB) {
        audioA.addEventListener('play', () => audioB.pause());
        audioB.addEventListener('play', () => audioA.pause());
      }
    }

    function audioCard(label, sample) {
      return `
        <div class="rounded-2xl border border-slate-700 bg-slate-950/60 p-5">
          <div class="flex items-center justify-between">
            <h3 class="text-2xl font-black text-white">${label}</h3>
            <span class="rounded-full bg-slate-800 px-2 py-1 text-xs text-slate-300">${sample.duration.toFixed(2)}s</span>
          </div>
          <audio id="audio-${label.toLowerCase()}" class="mt-4 w-full" controls preload="none" src="${escapeHtml(sample.file)}"></audio>
        </div>
      `;
    }

    function renderResults() {
      const lines = ['ttspeak blind results'];
      for (const bracket of DATA.brackets) {
        const b = bracketState(bracket.id);
        if (b.winner) {
          const sample = DATA.samples[b.winner];
          lines.push(`${bracket.lang} ${bracket.gender}: ${sample.model} / ${sample.voice}`);
        } else {
          lines.push(`${bracket.lang} ${bracket.gender}: pending`);
        }
      }
      const text = lines.join('\\n');
      document.getElementById('results').value = text;
      const completed = DATA.brackets.filter((bracket) => bracketState(bracket.id).winner).length;
      if (completed === DATA.brackets.length) {
        document.getElementById('copy-status').textContent = 'All six brackets complete. Copy this text and send it back.';
      } else {
        document.getElementById('copy-status').textContent = `${completed} of ${DATA.brackets.length} brackets complete.`;
      }
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }

    function render() {
      renderBrackets();
      renderActive();
      renderResults();
    }

    document.getElementById('reset-all').addEventListener('click', () => {
      if (!confirm('Reset all six brackets?')) return;
      state.active = null;
      state.brackets = {};
      saveState();
      render();
    });

    document.getElementById('copy-results').addEventListener('click', async () => {
      const textarea = document.getElementById('results');
      try {
        await navigator.clipboard.writeText(textarea.value);
        document.getElementById('copy-status').textContent = 'Copied to clipboard.';
      } catch (error) {
        textarea.select();
        document.execCommand('copy');
        document.getElementById('copy-status').textContent = 'Copied to clipboard.';
      }
    });

    document.addEventListener('keydown', (event) => {
      if (!state.active) return;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
      const bracket = bracketState(state.active);
      const match = currentMatch(bracket);
      if (!match) return;
      if (event.key.toLowerCase() === 'a') choose(match[0]);
      if (event.key.toLowerCase() === 'b') choose(match[1]);
    });

    render();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
