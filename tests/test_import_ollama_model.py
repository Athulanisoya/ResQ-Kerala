"""Only one complete, checksummed model may enter the Docker model cache."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tarfile

import pytest

from scripts import import_ollama_model as importer


@pytest.fixture
def cache(tmp_path):
    source = tmp_path / "models"
    manifest = source / "manifests/registry.ollama.ai/library/gemma4/e4b-it-q4_K_M"
    manifest.parent.mkdir(parents=True)
    records = []
    for content in [b"synthetic model configuration", b"synthetic model weights"]:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        path = source / "blobs" / digest.replace(":", "-", 1)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        records.append({"digest": digest, "size": len(content)})
    manifest.write_text(json.dumps({"config": records[0], "layers": [records[1]]}), encoding="utf-8")
    (source / "unrelated-private-file").write_text("synthetic private data", encoding="utf-8")
    return source, manifest, records


def test_archive_contains_only_verified_model_blobs_then_manifest(cache):
    source, manifest, records = cache
    bundle = importer.prepare_model(source)
    output = BytesIO()
    importer.write_archive(bundle, output)
    with tarfile.open(fileobj=BytesIO(output.getvalue())) as archive:
        assert archive.getnames() == [
            *("blobs/" + item["digest"].replace(":", "-", 1) for item in records),
            "manifests/registry.ollama.ai/library/gemma4/e4b-it-q4_K_M",
        ]
        for entry in archive.getmembers():
            assert entry.isfile()
            assert not entry.name.startswith("/") and ".." not in Path(entry.name).parts
        assert archive.extractfile(bundle.manifest_name).read() == manifest.read_bytes()
    assert (source / "unrelated-private-file").read_text() == "synthetic private data"


@pytest.mark.parametrize("model", [
    "../gemma4:latest", "registry.ollama.ai/library/gemma4:latest",
    "community/gemma4:latest", "gemma4", "gemma4:../latest", "gemma4:latest:extra",
])
def test_unqualified_or_path_like_model_names_are_rejected(cache, model):
    with pytest.raises(ValueError, match="official library model"):
        importer.prepare_model(cache[0], model)


@pytest.mark.parametrize("kind", ["missing", "corrupt"])
def test_incomplete_or_corrupt_blob_fails_before_any_container_mutation(cache, monkeypatch, kind):
    source, _, records = cache
    path = source / "blobs" / records[1]["digest"].replace(":", "-", 1)
    path.unlink() if kind == "missing" else path.write_bytes(b"corrupt weights")
    monkeypatch.setattr(importer.subprocess, "run", lambda *a, **k: pytest.fail("Docker must not run for an invalid cache"))
    with pytest.raises(SystemExit) as failure:
        importer.main(["--source", str(source)])
    assert failure.value.code == 1


@pytest.mark.parametrize("reference", ["sha256:../outside", "https://example.org/model", "sha256:" + "f" * 63])
def test_manifest_digest_cannot_choose_an_arbitrary_file(cache, reference):
    source, manifest, records = cache
    manifest.write_text(json.dumps({"config": records[0], "layers": [{"digest": reference}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid config or layer references"):
        importer.prepare_model(source)


def test_referenced_symlink_is_not_followed_even_to_matching_contents(cache, tmp_path):
    source, _, records = cache
    path = source / "blobs" / records[1]["digest"].replace(":", "-", 1)
    outside = tmp_path / "outside-model"
    path.replace(outside)
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links requires an enabled host privilege")
    with pytest.raises(ValueError, match="symbolic links"):
        importer.prepare_model(source)


def test_changed_file_after_verification_is_rejected_before_docker(cache, monkeypatch):
    bundle = importer.prepare_model(cache[0])
    bundle.blobs[0].path.write_bytes(b"changed cache")
    monkeypatch.setattr(importer.subprocess, "run", lambda *a, **k: pytest.fail("Docker must not run after the cache changed"))
    with pytest.raises(ValueError, match="changed after verification"):
        importer.import_model(bundle)


def test_duplicate_manifest_references_copy_each_blob_once(cache):
    source, manifest, records = cache
    manifest.write_text(json.dumps({"config": records[0], "layers": [records[1], records[1]]}), encoding="utf-8")
    assert len(importer.prepare_model(source).blobs) == 2


@pytest.mark.parametrize("exit_code", [0, 1])
def test_verified_subset_is_streamed_to_compose_and_failed_extraction_is_not_success(cache, monkeypatch, exit_code):
    bundle = importer.prepare_model(cache[0])
    commands = []

    class CapturedPipe(BytesIO):
        def close(self):
            self.saved = self.getvalue()
            super().close()

    class Process:
        stdin = CapturedPipe()
        returncode = None

        def wait(self):
            self.returncode = exit_code
            return exit_code

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -1

    process = Process()

    def run(command, **options):
        assert not options.get("shell")
        commands.append(command)

    def popen(command, **options):
        assert not options.get("shell")
        commands.append(command)
        return process

    monkeypatch.setattr(importer.subprocess, "run", run)
    monkeypatch.setattr(importer.subprocess, "Popen", popen)
    if exit_code:
        with pytest.raises(RuntimeError, match="could not import"):
            importer.import_model(bundle)
    else:
        importer.import_model(bundle)
    assert all(command[:7] == ["docker", "compose", "--env-file", ".env.docker", "exec", "-T", "ollama"] for command in commands)
    assert commands[-1][7:] == ["tar", "-xf", "-", "-C", "/root/.ollama/models"]
    with tarfile.open(fileobj=BytesIO(process.stdin.saved)) as archive:
        assert len(archive.getmembers()) == len(bundle.blobs) + 1
        assert archive.getnames()[-1] == bundle.manifest_name
