"""Detect chunk boundaries and loudness jumps in a TTS audio file.

This is a diagnostic tool, not part of the ttspeak runtime. It decodes WAV or
anything ffmpeg can read to mono PCM, computes short-term RMS in dBFS and
reports silence gaps plus the loudness step before/after each gap.

Usage:
  python tools/analyze_audio.py FILE [--json out.json] [--html out.html]
"""

from __future__ import annotations

import argparse
import array
import html
import itertools
import json
import math
import shutil
import subprocess
import sys
import wave
from pathlib import Path

SILENCE_DB = -45.0
MIN_GAP_SECONDS = 0.08
WINDOW_SECONDS = 0.05
BEFORE_AFTER_SECONDS = 0.40


def _db(value: float) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(value)


def load_samples(path: Path) -> tuple[array.array, int]:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as handle:
                channels = handle.getnchannels()
                width = handle.getsampwidth()
                rate = handle.getframerate()
                if width != 2:
                    raise SystemExit(f"Only 16-bit WAV is supported, got {width * 8}-bit.")
                raw = array.array("h")
                raw.frombytes(handle.readframes(handle.getnframes()))
        except (OSError, wave.Error) as exc:
            raise SystemExit(f"Cannot read WAV {path}: {exc}") from exc
        if channels == 1:
            return raw, rate
        if channels == 2:
            mono = array.array("h")
            mono.extend((raw[i] + raw[i + 1]) // 2 for i in range(0, len(raw) - 1, 2))
            return mono, rate
        raise SystemExit(f"Unsupported channel count: {channels}")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for non-WAV input.")
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "24000",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"ffmpeg failed: {detail}")
    samples = array.array("h")
    samples.frombytes(result.stdout)
    return samples, 24000


def rms_windows(samples: array.array, rate: int) -> list[dict[str, float]]:
    size = max(1, int(rate * WINDOW_SECONDS))
    result: list[dict[str, float]] = []
    for start in range(0, len(samples), size):
        block = samples[start : start + size]
        if not block:
            continue
        energy = sum(value * value for value in block) / len(block)
        result.append(
            {
                "time": start / rate,
                "db": _db(math.sqrt(energy) / 32768.0),
            }
        )
    return result


def median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return -120.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _values_between(
    windows: list[dict[str, float]],
    start: float,
    end: float,
) -> list[float]:
    return [item["db"] for item in windows if start <= item["time"] < end]


def find_gaps(windows: list[dict[str, float]]) -> list[dict[str, float]]:
    gaps: list[dict[str, float]] = []
    start: float | None = None
    for item in windows:
        if item["db"] <= SILENCE_DB:
            if start is None:
                start = item["time"]
        elif start is not None:
            end = item["time"]
            if end - start >= MIN_GAP_SECONDS:
                gaps.append({"start": start, "end": end, "seconds": end - start})
            start = None
    return gaps


def add_boundary_stats(
    windows: list[dict[str, float]],
    gaps: list[dict[str, float]],
) -> list[dict[str, float]]:
    boundaries: list[dict[str, float]] = []
    for gap in gaps:
        before = _values_between(
            windows,
            gap["start"] - BEFORE_AFTER_SECONDS,
            gap["start"],
        )
        after = _values_between(
            windows,
            gap["end"],
            gap["end"] + BEFORE_AFTER_SECONDS,
        )
        if not before or not after:
            continue
        before_db = median(before)
        after_db = median(after)
        onset = gap["end"]
        threshold = before_db + 4.0
        for item in windows:
            if item["time"] >= gap["end"] and item["db"] >= threshold:
                onset = item["time"]
                break
        boundaries.append(
            {
                **gap,
                "before_db": before_db,
                "after_db": after_db,
                "delta_db": after_db - before_db,
                "onset": onset,
            }
        )
    return boundaries


def find_jumps(windows: list[dict[str, float]], threshold_db: float) -> list[dict[str, float]]:
    jumps: list[dict[str, float]] = []
    for previous, current in itertools.pairwise(windows):
        if previous["db"] <= SILENCE_DB or current["db"] <= SILENCE_DB:
            continue
        delta = current["db"] - previous["db"]
        if abs(delta) >= threshold_db:
            jumps.append(
                {
                    "time": current["time"],
                    "before_db": previous["db"],
                    "after_db": current["db"],
                    "delta_db": delta,
                }
            )
    return jumps


def timecode(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:05.2f}"


def print_report(
    path: Path,
    duration: float,
    boundaries: list[dict[str, float]],
    jumps: list[dict[str, float]],
    *,
    min_step: float,
    max_gap: float,
) -> None:
    print(f"File:     {path}")
    print(f"Duration: {duration:.2f}s ({timecode(duration)})")
    print(f"Window:   {WINDOW_SECONDS * 1000:.0f} ms, silence <= {SILENCE_DB:.0f} dBFS")
    loud_starts = [
        item
        for item in boundaries
        if item["delta_db"] >= min_step and item["seconds"] <= max_gap
    ]
    print()
    print(
        f"Positive loudness steps at short silence gaps (>= {min_step:.0f} dB, "
        f"gap <= {max_gap:.2f}s):"
    )
    print(f"{'#':>3}  {'gap start':>10}  {'gap end':>10}  {'gap':>6}  "
          f"{'before':>8}  {'after':>8}  {'delta':>8}  onset")
    for index, item in enumerate(loud_starts, 1):
        print(
            f"{index:>3}  {timecode(item['start']):>10}  {timecode(item['end']):>10}  "
            f"{item['seconds']:>6.2f}  {item['before_db']:>8.1f}  {item['after_db']:>8.1f}  "
            f"{item['delta_db']:>+8.1f}  {timecode(item['onset'])}"
        )
    print()
    largest = max((item["delta_db"] for item in loud_starts), default=0.0)
    print(
        f"Chunk-start candidates: {len(loud_starts)}; largest positive step: "
        f"{largest:+.1f} dB"
    )
    print(f"All silence gaps: {len(boundaries)}; abrupt in-speech 50-ms jumps >= 8 dB: "
          f"{len(jumps)}")
    for item in sorted(jumps, key=lambda item: abs(item["delta_db"]), reverse=True)[:15]:
        print(
            f"  {timecode(item['time'])}  {item['before_db']:>7.1f} -> "
            f"{item['after_db']:>7.1f} dB  ({item['delta_db']:+.1f})"
        )


def build_html(
    path: Path,
    duration: float,
    windows: list[dict[str, float]],
    boundaries: list[dict[str, float]],
    jumps: list[dict[str, float]],
    *,
    min_step: float,
    max_gap: float,
) -> str:
    loud_starts = [
        item
        for item in boundaries
        if item["delta_db"] >= min_step and item["seconds"] <= max_gap
    ]
    width, height, pad = 1400, 380, 44
    plot_width = width - 2 * pad
    plot_height = height - 2 * pad
    step = max(1, len(windows) // 3000)
    points = windows[::step]
    coords = []
    for item in points:
        x = pad + (item["time"] / duration if duration else 0) * plot_width
        y = pad + (max(-60.0, min(0.0, item["db"])) / -60.0) * plot_height
        coords.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(coords)
    gap_lines = []
    for item in loud_starts:
        x = pad + (item["start"] / duration if duration else 0) * plot_width
        gap_lines.append(
            f'<line x1="{x:.1f}" y1="{pad}" x2="{x:.1f}" y2="{height - pad}" '
            f'stroke="#d62728" stroke-width="1.4" stroke-dasharray="5 3" />'
        )
    top = sorted(loud_starts, key=lambda item: item["start"])
    rows = "\n".join(
        f"<tr><td>{timecode(item['start'])}</td><td>{timecode(item['end'])}</td>"
        f"<td>{item['seconds']:.3f}</td><td>{item['before_db']:.1f}</td>"
        f"<td>{item['after_db']:.1f}</td><td>{item['delta_db']:+.1f}</td>"
        f"<td>{timecode(item['onset'])}</td></tr>"
        for item in top
    )
    jump_rows = "\n".join(
        f"<tr><td>{timecode(item['time'])}</td><td>{item['before_db']:.1f}</td>"
        f"<td>{item['after_db']:.1f}</td><td>{item['delta_db']:+.1f}</td></tr>"
        for item in sorted(jumps, key=lambda item: abs(item["delta_db"]), reverse=True)[:20]
    )
    title = html.escape(path.name)
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>ttspeak audio analysis — {title}</title>
<style>
  body {{ font: 15px/1.45 -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #222; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
  .meta {{ color: #666; }}
  svg {{ width: 100%; height: auto; background: #fafafa; border: 1px solid #ddd; }}
  table {{ border-collapse: collapse; margin-top: 8px; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: 5px 10px; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  .note {{ color: #666; }}
</style>
<h1>ttspeak audio analysis — {title}</h1>
<p class="meta">Duration {timecode(duration)} · {len(loud_starts)} chunk-start candidates ≥ {min_step:.0f} dB · {len(jumps)} in-speech jumps ≥ 8 dB</p>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="Short-term RMS over time">
  <text x="{pad}" y="24" font-size="13" fill="#666">0 dBFS</text>
  <text x="{pad}" y="{height - 12}" font-size="13" fill="#666">-60 dBFS</text>
  {''.join(gap_lines)}
  <polyline points="{polyline}" fill="none" stroke="#1f77b4" stroke-width="1.2" />
</svg>
<p class="note">Blue: 50 ms RMS. Red dashed: silence gap with a positive loudness step (chunk-start candidate).</p>
<h2>Positive loudness steps at silence gaps</h2>
<table><tr><th>gap start</th><th>gap end</th><th>gap s</th><th>before dB</th><th>after dB</th><th>delta</th><th>onset</th></tr>
{rows}
</table>
<h2>Abrupt in-speech 50-ms jumps</h2>
<table><tr><th>time</th><th>before dB</th><th>after dB</th><th>delta</th></tr>
{jump_rows}
</table>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--json", type=Path, help="write full machine-readable analysis")
    parser.add_argument("--html", type=Path, help="write an HTML report")
    parser.add_argument(
        "--min-step",
        type=float,
        default=10.0,
        help="minimum positive dB step at a silence gap for a chunk-start candidate",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=0.30,
        help="maximum silence-gap length in seconds for a chunk-start candidate",
    )
    args = parser.parse_args(argv)

    if not args.file.is_file():
        raise SystemExit(f"File not found: {args.file}")
    samples, rate = load_samples(args.file)
    if not samples:
        raise SystemExit("No audio samples decoded.")
    windows = rms_windows(samples, rate)
    duration = len(samples) / rate
    gaps = find_gaps(windows)
    boundaries = add_boundary_stats(windows, gaps)
    jumps = find_jumps(windows, threshold_db=8.0)
    loud_starts = [
        item
        for item in boundaries
        if item["delta_db"] >= args.min_step and item["seconds"] <= args.max_gap
    ]

    print_report(
        args.file,
        duration,
        boundaries,
        jumps,
        min_step=args.min_step,
        max_gap=args.max_gap,
    )

    data = {
        "file": str(args.file),
        "duration": duration,
        "sample_rate": rate,
        "window_seconds": WINDOW_SECONDS,
        "silence_db": SILENCE_DB,
        "min_step_db": args.min_step,
        "max_gap_seconds": args.max_gap,
        "chunk_start_candidates": loud_starts,
        "boundaries": boundaries,
        "jumps": jumps,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"\nJSON: {args.json}")
    if args.html:
        args.html.parent.mkdir(parents=True, exist_ok=True)
        args.html.write_text(
            build_html(
                args.file,
                duration,
                windows,
                boundaries,
                jumps,
                min_step=args.min_step,
                max_gap=args.max_gap,
            ),
            encoding="utf-8",
        )
        print(f"HTML: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
