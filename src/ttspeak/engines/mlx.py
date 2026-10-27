"""MLX backend: isolated runtime venv + worker subprocess."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..errors import EngineError
from ..util import utc_now, write_json
from .base import SynthesisRequest, SynthesisResult

MLX_MIN_PYTHON = (3, 10)


@dataclass
class RuntimeStatus:
    python: Path | None
    healthy: bool
    detail: str
    version: str | None = None


def _run(
    command: list[str],
    *,
    check: bool = False,
    capture: bool = True,
    timeout: float = 1800,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise EngineError(f"Executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise EngineError(
            f"Command failed ({' '.join(command)}): {detail or exc.returncode}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineError(f"Command timed out after {timeout:.0f}s: {' '.join(command)}") from exc


def check_python(python: Path) -> RuntimeStatus:
    if not python.exists():
        return RuntimeStatus(python=None, healthy=False, detail=f"{python} does not exist")
    probe = (
        "import json, sys\n"
        "import mlx_audio, mlx.core\n"
        "try:\n"
        "    from importlib.metadata import version as _version\n"
        "    _mlx_version = _version('mlx-audio')\n"
        "except Exception:\n"
        "    _mlx_version = getattr(mlx_audio, '__version__', 'unknown')\n"
        "print(json.dumps({'version': _mlx_version,"
        " 'python': sys.version.split()[0]}))\n"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", probe],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RuntimeStatus(python=python, healthy=False, detail=str(exc))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "import failed").strip().splitlines()[-1]
        return RuntimeStatus(python=python, healthy=False, detail=detail)
    try:
        info = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        info = {}
    return RuntimeStatus(
        python=python,
        healthy=True,
        detail=f"Python {info.get('python', '?')}, mlx-audio {info.get('version', 'unknown')}",
        version=info.get("version"),
    )


def find_runtime(*, required: bool = True) -> RuntimeStatus:
    candidates: list[tuple[Path, str]] = []
    override = os.environ.get("TTSPEAK_PYTHON")
    if override:
        candidates.append((Path(override).expanduser(), "TTSPEAK_PYTHON"))
    candidates.append((paths.runtime_python(), f"managed runtime ({paths.runtime_dir()})"))
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append((Path(found), "PATH"))

    seen: set[Path] = set()
    last: RuntimeStatus | None = None
    for python, source in candidates:
        resolved = python.resolve() if python.exists() else python
        if resolved in seen:
            continue
        seen.add(resolved)
        status = check_python(python)
        if status.healthy:
            return status
        last = RuntimeStatus(
            python=python,
            healthy=False,
            detail=f"{source}: {status.detail}",
            version=None,
        )

    if required:
        target = paths.runtime_python()
        detail = last.detail if last else "no Python interpreter found"
        raise EngineError(
            "No working mlx-audio runtime found "
            f"({detail}). Install it with: ttspeak runtime install\n"
            f"Expected runtime: {target}"
        )
    return last or RuntimeStatus(python=None, healthy=False, detail="no Python interpreter found")


def runtime_status() -> RuntimeStatus:
    override = os.environ.get("TTSPEAK_PYTHON")
    if override:
        return check_python(Path(override).expanduser())
    managed = paths.runtime_python()
    if managed.exists():
        return check_python(managed)
    return find_runtime(required=False)


def _pip_spec(version: str | None) -> str:
    return f"mlx-audio=={version}" if version else "mlx-audio"


def _python_version(python: Path) -> tuple[int, int]:
    result = _run([str(python), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"])
    try:
        major, minor = result.stdout.strip().split(".")
        return int(major), int(minor)
    except (ValueError, AttributeError) as exc:
        raise EngineError(f"Could not determine Python version of {python}") from exc


def install_runtime(
    *,
    python: Path | None = None,
    version: str | None = None,
    force: bool = False,
) -> RuntimeStatus:
    if force and paths.runtime_dir().exists():
        shutil.rmtree(paths.runtime_dir())

    existing = runtime_status()
    if existing.healthy and not force:
        return existing

    paths.runtime_dir().mkdir(parents=True, exist_ok=True)
    venv = paths.runtime_dir() / "venv"
    venv_python = venv / "bin" / "python"

    host_python = python or Path(shutil.which("python3") or sys.executable)
    if not host_python.exists():
        raise EngineError(f"Python interpreter not found: {host_python}")
    if _python_version(host_python) < MLX_MIN_PYTHON:
        raise EngineError(f"Python {host_python} is too old; mlx-audio needs >= 3.10.")

    uv = shutil.which("uv")
    print(
        f"Creating MLX runtime at {venv} "
        f"(using {'uv' if uv else 'venv/pip'}, source {host_python})",
        file=sys.stderr,
    )
    if uv:
        _run([uv, "venv", "--python", str(host_python), str(venv)], check=True, capture=False)
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(venv_python),
                "--prerelease=allow",
                _pip_spec(version),
            ],
            check=True,
            capture=False,
        )
    else:
        _run([str(host_python), "-m", "venv", str(venv)], check=True, capture=False)
        _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True, capture=False)
        _run(
            [str(venv_python), "-m", "pip", "install", "--pre", _pip_spec(version)],
            check=True,
            capture=False,
        )

    status = check_python(venv_python)
    if not status.healthy:
        raise EngineError(
            f"Runtime was created but mlx-audio does not import: {status.detail}"
        )
    write_json(
        paths.runtime_dir() / "runtime.json",
        {
            "python": str(venv_python),
            "source_python": str(host_python),
            "mlx_audio": status.version,
            "installed_at": utc_now(),
        },
        private=True,
    )
    return status


class MlxEngine:
    name = "mlx"

    def __init__(self, status: RuntimeStatus | None = None) -> None:
        if sys.platform != "darwin":
            raise EngineError("The mlx engine requires macOS on Apple Silicon.")
        if os.uname().machine not in {"arm64", "aarch64"}:
            raise EngineError("The mlx engine requires an Apple Silicon Mac (arm64).")
        self.status = status or find_runtime()

    def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if request.model_path is None:
            raise EngineError("The mlx engine needs a local model path.")
        if not request.model_path.is_dir():
            raise EngineError(f"Model directory not found: {request.model_path}")
        assert self.status.python is not None

        worker = Path(__file__).resolve().parent.parent / "worker_mlx.py"
        if not worker.exists():
            raise EngineError(f"Worker script is missing: {worker}")

        paths.tmp_dir().mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="run-", dir=paths.tmp_dir()))
        request_path = workdir / "request.json"
        result_path = workdir / "result.json"
        payload = {
            "model_path": str(request.model_path),
            "method": request.method,
            "text": request.text,
            "output": str(request.output),
            "result_path": str(result_path),
            "speaker": request.speaker,
            "language": request.language,
            "instruct": request.instruct,
            "speed": request.speed,
            "ref_audio": str(request.ref_audio) if request.ref_audio else None,
            "ref_text": request.ref_text,
        }
        write_json(request_path, payload)

        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env.pop("PYTHONPATH", None)

        try:
            completed = subprocess.run(
                [str(self.status.python), str(worker), str(request_path)],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=sys.stderr,
                stderr=None,
                env=env,
                timeout=1800,
            )
        except subprocess.TimeoutExpired as exc:
            raise EngineError(
                f"Speech generation timed out after 30 minutes. Request kept at {workdir}"
            ) from exc

        if not result_path.exists():
            raise EngineError(
                f"The MLX worker produced no result (exit {completed.returncode}). "
                f"Request kept at {workdir}"
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            raise EngineError(f"MLX generation failed: {result.get('error', 'unknown error')}")
        output = Path(result["output"])
        if not output.is_file():
            raise EngineError(f"Worker reported success but {output} is missing.")
        shutil.rmtree(workdir, ignore_errors=True)
        return SynthesisResult(
            output=output,
            duration=float(result.get("duration", 0.0)),
            sample_rate=int(result.get("sample_rate", 24000)),
            chunks=int(result.get("chunks", 1)),
        )
