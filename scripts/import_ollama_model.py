"""Copy one verified official local Ollama model into the Compose model volume."""
import argparse
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gemma4:e4b-it-q4_K_M"
MODEL_PATTERN = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,99}):([A-Za-z0-9][A-Za-z0-9._-]{0,99})")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
COMPOSE = ["docker", "compose", "--env-file", ".env.docker", "exec", "-T", "ollama"]


@dataclass(frozen=True)
class Blob:
    path: Path
    archive_name: str
    size: int
    fingerprint: tuple


@dataclass(frozen=True)
class ModelBundle:
    model: str
    source: Path
    manifest_name: str
    manifest: bytes
    blobs: tuple[Blob, ...]


def _fingerprint(details):
    return (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)


def _regular_file(source: Path, relative: Path) -> Path:
    candidate = source / relative
    for component in [source, *(source / Path(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1))]:
        try:
            details = component.lstat()
        except OSError:
            raise ValueError("The selected model manifest or a referenced blob is missing.") from None
        if (stat.S_ISLNK(details.st_mode)
                or getattr(details, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Model import does not follow symbolic links or directory junctions.")
    if not candidate.resolve().is_relative_to(source.resolve()) or not candidate.is_file():
        raise ValueError("Every model file must be a regular file within the selected model directory.")
    return candidate


def prepare_model(source: Path, model: str = DEFAULT_MODEL) -> ModelBundle:
    """Validate every file and checksum before changing the container volume."""
    match = MODEL_PATTERN.fullmatch(model)
    if not match:
        raise ValueError("Use an official library model with a simple name:tag, without registry or namespace paths.")
    source = Path(source).expanduser().absolute()
    name, tag = match.groups()
    manifest_name = f"manifests/registry.ollama.ai/library/{name}/{tag}"
    manifest_path = _regular_file(source, Path(manifest_name))
    if manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("The selected model manifest is unexpectedly large.")
    try:
        manifest = manifest_path.read_bytes()
        metadata = json.loads(manifest)
        references = [metadata["config"], *metadata["layers"]]
        if not isinstance(metadata["layers"], list) or not metadata["layers"]:
            raise ValueError
        digests = [entry["digest"] for entry in references]
        if not all(isinstance(digest, str) and DIGEST_PATTERN.fullmatch(digest) for digest in digests):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ValueError("The selected model manifest has invalid config or layer references.") from None
    blobs = []
    for digest in dict.fromkeys(digests):
        archive_name = "blobs/" + digest.replace(":", "-", 1)
        path = _regular_file(source, Path(archive_name))
        details = path.stat()
        checksum = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(chunk)
        if checksum.hexdigest() != digest.removeprefix("sha256:"):
            raise ValueError("A model blob failed SHA256 verification. Preserve the host cache and retry after repairing that model.")
        if _fingerprint(path.stat()) != _fingerprint(details):
            raise ValueError("A model file changed during verification. Wait for local model downloads to finish and retry.")
        blobs.append(Blob(path, archive_name, details.st_size, _fingerprint(details)))
    return ModelBundle(model, source, manifest_name, manifest, tuple(blobs))


def _validate_unchanged(bundle: ModelBundle):
    for blob in bundle.blobs:
        path = _regular_file(bundle.source, Path(blob.archive_name))
        if _fingerprint(path.stat()) != blob.fingerprint:
            raise ValueError("A model file changed after verification. Wait for local model downloads to finish and retry.")


def write_archive(bundle: ModelBundle, output):
    """Stream only verified blobs and the final manifest; never host credentials."""
    with tarfile.open(fileobj=output, mode="w|") as archive:
        for blob in bundle.blobs:
            _regular_file(bundle.source, Path(blob.archive_name))
            with blob.path.open("rb") as handle:
                if _fingerprint(os.fstat(handle.fileno())) != blob.fingerprint:
                    raise ValueError("A model file changed after verification. Retry the import.")
                entry = tarfile.TarInfo(blob.archive_name)
                entry.size = blob.size
                entry.mode = 0o644
                archive.addfile(entry, handle)
        # Publish the manifest only after all of its referenced blobs are copied.
        entry = tarfile.TarInfo(bundle.manifest_name)
        entry.size = len(bundle.manifest)
        entry.mode = 0o644
        archive.addfile(entry, BytesIO(bundle.manifest))


def import_model(bundle: ModelBundle):
    _validate_unchanged(bundle)
    subprocess.run(
        [*COMPOSE, "mkdir", "-p", "/root/.ollama/models"],
        cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    process = subprocess.Popen(
        [*COMPOSE, "tar", "-xf", "-", "-C", "/root/.ollama/models"],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        write_archive(bundle, process.stdin)
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("The container could not import the model. Confirm the Compose Ollama service is running and has free disk space.")
    except BaseException:
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    try:
        bundle = prepare_model(args.source, args.model)
        print(f"Verified {len(bundle.blobs)} SHA256 blobs for {bundle.model}; copying to the Docker Ollama volume.", flush=True)
        import_model(bundle)
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        parser.exit(1, "Model import failed. Check the official model name, complete host cache, running Compose Ollama service and available disk space. Host files were not changed.\n")
    print(f"Imported {bundle.model}. Start the complete stack with docker compose --env-file .env.docker up -d --build.")


if __name__ == "__main__":
    main()
