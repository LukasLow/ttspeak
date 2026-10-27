"""Model store: Hugging Face downloads, listing, removal, pruning."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .errors import ModelNotFound, ModelNotInstalled, UsageError
from .registry import ModelSpec, resolve_model
from .util import confirm, human_size, read_json, sha256_file, slugify, utc_now, write_json

MANIFEST_NAME = ".ttspeak-manifest.json"
CHUNK_SIZE = 1024 * 1024
USER_AGENT = "ttspeak/0.1 (+https://github.com/lukas/ttspeak)"


@dataclass
class InstalledModel:
    spec: ModelSpec
    path: Path
    manifest: dict[str, Any]

    @property
    def size_bytes(self) -> int:
        total = self.manifest.get("total_size")
        if isinstance(total, int):
            return total
        return sum(int(item.get("size") or 0) for item in self.manifest.get("files", []))

    @property
    def installed_at(self) -> str:
        return str(self.manifest.get("installed_at", ""))

    @property
    def revision(self) -> str:
        return str(self.manifest.get("revision", ""))


def model_path(model_id: str) -> Path:
    return paths.models_dir() / slugify(model_id)


def _manifest_path(path: Path) -> Path:
    return path / MANIFEST_NAME


def _load_installed(path: Path) -> InstalledModel | None:
    manifest = read_json(_manifest_path(path), default=None)
    if not isinstance(manifest, dict):
        return None
    spec_data = manifest.get("spec")
    if not isinstance(spec_data, dict):
        return None
    try:
        spec = ModelSpec.from_dict(spec_data)
    except ValueError:
        return None
    return InstalledModel(spec=spec, path=path, manifest=manifest)


def list_installed() -> list[InstalledModel]:
    root = paths.models_dir()
    if not root.is_dir():
        return []
    found: list[InstalledModel] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        installed = _load_installed(entry)
        if installed is not None:
            found.append(installed)
    return found


def is_installed(model_id: str) -> bool:
    return _load_installed(model_path(model_id)) is not None


def get_installed(model_id: str) -> InstalledModel | None:
    return _load_installed(model_path(model_id))


def require_installed(model_id: str) -> InstalledModel:
    installed = get_installed(model_id)
    if installed is None:
        raise ModelNotInstalled(
            f"Model {model_id} is not installed. Run: ttspeak pull {model_id}"
        )
    return installed


class PullProgress:
    """Human-readable download progress, quiet when stderr is not a TTY."""

    def __init__(self, stream=None) -> None:
        self.stream = stream or sys.stderr
        self.tty = hasattr(self.stream, "isatty") and self.stream.isatty()

    def start(self, index: int, count: int, name: str, size: int | None) -> None:
        label = human_size(size) if size else "unknown size"
        print(f"  [{index}/{count}] {name} ({label})", file=self.stream)

    def update(self, name: str, done: int, total: int | None) -> None:
        if not self.tty:
            return
        if total:
            percent = done * 100 / total
            line = f"\r      {human_size(done)} / {human_size(total)}  {percent:5.1f}%"
        else:
            line = f"\r      {human_size(done)}"
        self.stream.write(line)
        self.stream.flush()

    def finish(self, name: str, done: int, total: int | None) -> None:
        if self.tty:
            self.stream.write("\n")
            self.stream.flush()


ProgressCallback = Callable[[str, str, int, int | None], None]


def _hf_endpoint() -> str:
    return os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")


def _request(url: str, token: str | None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _http_error_message(url: str, exc: urllib.error.HTTPError) -> str:
    if exc.code in (401, 403):
        return (
            f"Access denied for {url}. The model may be gated; set HF_TOKEN with access."
        )
    if exc.code == 404:
        return f"Not found: {url}"
    if exc.code == 429:
        return f"Rate limited by Hugging Face while requesting {url}. Try again later."
    return f"HTTP {exc.code} for {url}: {exc.reason}"


def fetch_hf_files(repo: str, token: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Return (revision, files) for a Hugging Face model repository."""
    api_url = f"{_hf_endpoint()}/api/models/{repo}?blobs=true"
    try:
        with urllib.request.urlopen(_request(api_url, token), timeout=60) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ModelNotInstalled(_http_error_message(api_url, exc)) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ModelNotInstalled(f"Could not reach Hugging Face: {exc}") from exc

    revision = str(data.get("sha") or "main")
    files: list[dict[str, Any]] = []
    for sibling in data.get("siblings", []):
        name = sibling.get("rfilename")
        if not name:
            continue
        size = sibling.get("size")
        if size is None and isinstance(sibling.get("lfs"), dict):
            size = sibling["lfs"].get("size")
        sha256 = None
        if isinstance(sibling.get("lfs"), dict):
            sha256 = sibling["lfs"].get("sha256")
        files.append({"path": name, "size": size, "sha256": sha256, "repo": repo})
    if not files:
        raise ModelNotInstalled(f"Repository {repo} contains no downloadable files.")
    return revision, files


def _static_files(spec: ModelSpec) -> tuple[str, list[dict[str, Any]]]:
    if not spec.files:
        raise ModelNotInstalled(f"Static model {spec.id} has no file list.")
    files = []
    for entry in spec.files:
        item = dict(entry)
        if "url" not in item:
            raise ModelNotInstalled(f"Static file entry for {spec.id} needs a url: {entry!r}")
        files.append(item)
    return str(spec.extra.get("revision", "static")), files


def _safe_relative(name: str) -> Path:
    """Reject absolute paths and parent traversal from remote file lists."""
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise UsageError(f"Unsafe file path in model metadata: {name!r}")
    return relative


def _download(
    url: str,
    dest: Path,
    *,
    expected_size: int | None,
    expected_sha256: str | None,
    token: str | None,
    on_chunk: Callable[[int, int | None], None] | None = None,
) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        if expected_sha256:
            if sha256_file(dest) == expected_sha256:
                return dest.stat().st_size
        else:
            return dest.stat().st_size

    offset = part.stat().st_size if part.exists() else 0
    if expected_size is not None and offset > expected_size:
        part.unlink()
        offset = 0

    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if offset:
        headers["Range"] = f"bytes={offset}-"

    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        raise ModelNotInstalled(_http_error_message(url, exc)) from exc
    except urllib.error.URLError as exc:
        raise ModelNotInstalled(f"Download failed for {url}: {exc.reason}") from exc

    with response:
        status = getattr(response, "status", None)
        if offset and status != 206:
            offset = 0
            part.unlink(missing_ok=True)
        mode = "ab" if offset else "wb"
        written = offset
        with part.open(mode) as handle:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if on_chunk:
                    on_chunk(written, expected_size)
        total = written

    if expected_size is not None and total != expected_size:
        part.unlink(missing_ok=True)
        raise ModelNotInstalled(
            f"Size mismatch for {url}: expected {expected_size} bytes, got {total}."
        )
    if expected_sha256:
        actual = sha256_file(part)
        if actual != expected_sha256:
            part.unlink(missing_ok=True)
            raise ModelNotInstalled(
                f"Checksum mismatch for {url}: expected {expected_sha256}, got {actual}."
            )
    os.replace(part, dest)
    return total


def _acquire_lock(lock: Path) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise UsageError(
            f"Another pull seems to be running (lock: {lock}). "
            "If no other ttspeak process is active, delete the lock file."
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started": utc_now()}, handle)


def pull_model(
    query: str,
    *,
    force: bool = False,
    revision: str | None = None,
    token: str | None = None,
    progress: PullProgress | None = None,
) -> InstalledModel:
    spec = resolve_model(query)
    target = model_path(spec.id)
    lock = paths.models_dir() / f".{slugify(spec.id)}.lock"
    partial = paths.models_dir() / f".{slugify(spec.id)}.partial"

    if target.exists() and not force:
        installed = _load_installed(target)
        if installed is not None:
            return installed
        raise UsageError(
            f"{target} exists but has no valid manifest. Re-run with --force to replace it."
        )

    paths.models_dir().mkdir(parents=True, exist_ok=True)
    _acquire_lock(lock)
    progress = progress or PullProgress()
    try:
        if spec.source == "hf":
            resolved_revision, files = fetch_hf_files(spec.repo, token=token or os.environ.get("HF_TOKEN"))
        elif spec.source == "static":
            resolved_revision, files = _static_files(spec)
        else:
            raise UsageError(f"Unsupported model source '{spec.source}'.")

        partial.mkdir(parents=True, exist_ok=True)
        downloaded: list[dict[str, Any]] = []
        total_bytes = 0
        endpoint = _hf_endpoint()
        for index, file in enumerate(files, start=1):
            relative = _safe_relative(str(file["path"])).as_posix()
            size = file.get("size")
            sha256 = file.get("sha256")
            if file.get("url"):
                url = str(file["url"])
            elif spec.source == "hf":
                quoted = urllib.parse.quote(relative, safe="/")
                rev = revision or resolved_revision
                url = f"{endpoint}/{spec.repo}/resolve/{rev}/{quoted}?download=true"
            else:
                raise UsageError(f"No url for {relative}.")

            progress.start(index, len(files), relative, size)
            last_update = 0.0

            def on_chunk(done: int, total: int | None, name: str = relative) -> None:
                nonlocal last_update
                now = time.monotonic()
                if now - last_update >= 0.25:
                    progress.update(name, done, total)
                    last_update = now

            written = _download(
                url,
                partial / relative,
                expected_size=size,
                expected_sha256=sha256,
                token=token or os.environ.get("HF_TOKEN"),
                on_chunk=on_chunk,
            )
            progress.finish(relative, written, size)
            total_bytes += written
            downloaded.append({"path": relative, "size": written, "sha256": sha256})

        manifest = {
            "format": 1,
            "id": spec.id,
            "repo": spec.repo,
            "revision": resolved_revision,
            "installed_at": utc_now(),
            "total_size": total_bytes,
            "files": downloaded,
            "spec": spec.to_manifest(),
        }
        write_json(partial / MANIFEST_NAME, manifest)

        if target.exists():
            shutil.rmtree(target)
        os.replace(partial, target)
        installed = _load_installed(target)
        if installed is None:
            raise ModelNotInstalled(f"Pull of {spec.id} produced an unreadable manifest.")
        return installed
    finally:
        lock.unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    shutil.rmtree(path)


def resolve_installed_or_registry(query: str) -> ModelSpec:
    """Resolve a model id even when its registry entry has disappeared."""
    try:
        return resolve_model(query)
    except ModelNotFound:
        for item in list_installed():
            if query in {
                item.spec.id,
                item.spec.repo,
                item.path.name,
                slugify(item.spec.id),
            }:
                return item.spec
        raise


def remove_model(model_id: str, *, assume_yes: bool = False) -> Path:
    spec = resolve_installed_or_registry(model_id)
    target = model_path(spec.id)
    if not target.exists():
        raise ModelNotInstalled(f"Model {spec.id} is not installed.")
    if not confirm(f"Remove model {spec.id} and its weights at {target}?", assume_yes=assume_yes):
        raise UsageError("Cancelled.")
    _remove_path(target)
    return target


def prune_models(keep: Iterable[str], *, assume_yes: bool = False) -> list[str]:
    keep_ids = {resolve_model(item).id for item in keep}
    removable = [item for item in list_installed() if item.spec.id not in keep_ids]
    if not removable:
        return []
    names = ", ".join(item.spec.id for item in removable)
    if not confirm(f"Remove {len(removable)} model(s): {names}?", assume_yes=assume_yes):
        raise UsageError("Cancelled.")
    from .voices import list_profiles

    used_by_voices = {profile.model for profile in list_profiles()}
    for item in removable:
        if item.spec.id in used_by_voices:
            print(
                f"warning: a voice profile uses {item.spec.id}; it will stop working.",
                file=sys.stderr,
            )
    removed: list[str] = []
    for item in removable:
        _remove_path(item.path)
        removed.append(item.spec.id)
    return removed


def describe_installed(item: InstalledModel) -> dict[str, Any]:
    return {
        "id": item.spec.id,
        "repo": item.spec.repo,
        "revision": item.revision,
        "installed_at": item.installed_at,
        "size_bytes": item.size_bytes,
        "path": str(item.path),
        "method": item.spec.method,
    }
