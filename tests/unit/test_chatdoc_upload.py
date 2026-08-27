import json
from pathlib import Path

import pytest

from app.ingest.chatdoc_upload import (
    prepare_uploads,
    run_ingest,
)
from ingest_chatdoc import ChatDocIngestSettings


def test_ingest_settings_require_only_chatdoc_credentials():
    settings = ChatDocIngestSettings(
        _env_file=None,
        xf_app_id="app-id",
        xf_embedding_api_secret="shared-secret",
    )

    assert settings.xf_app_id == "app-id"
    assert settings.xf_embedding_api_secret.get_secret_value() == "shared-secret"


def test_prepare_uploads_keeps_small_pdf_and_maps_relative_source(tmp_path):
    root = tmp_path / "knowledge"
    source = root / "论文" / "sample.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"%PDF-small")

    prepared, skipped = prepare_uploads(root, max_file_bytes=20_000)

    assert len(prepared) == 1
    assert skipped == []
    assert prepared[0].source == "论文/sample.pdf"
    assert prepared[0].path == source


def test_prepare_uploads_skips_oversized_file(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    source = root / "large.pdf"
    source.write_bytes(b"x" * 101)

    prepared, skipped = prepare_uploads(root, max_file_bytes=100)

    assert prepared == []
    assert skipped == [
        {"source": "large.pdf", "reason": "oversized", "size_bytes": 101}
    ]


class FakeChatDoc:
    def __init__(self):
        self.uploaded = []
        self.added_batches = []

    async def create_repo(self, name, description=""):
        return "repo-123"

    async def upload_file(self, path, *, upload_name=None):
        file_id = f"file-{len(self.uploaded):03d}"
        self.uploaded.append((Path(path), upload_name, file_id))
        return file_id

    async def wait_until_vectored(self, file_ids, **kwargs):
        return {file_id: "vectored" for file_id in file_ids}

    async def add_files(self, repo_id, file_ids):
        self.added_batches.append((repo_id, list(file_ids)))


@pytest.mark.asyncio
async def test_run_ingest_publishes_manifest_after_vectoring_and_batches_adds(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    for index in range(21):
        (root / f"doc-{index:02d}.md").write_text(f"document {index}")
    artifact = tmp_path / "artifacts" / "base.json"
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=value\nXF_CHATDOC_REPO_ID=old-repo\n")
    client = FakeChatDoc()

    result = await run_ingest(
        client=client,
        source_root=root,
        artifact_path=artifact,
        env_file=env_file,
        repo_name="粮食储藏知识库-test",
    )

    manifest = json.loads(artifact.read_text())
    assert result.repo_id == "repo-123"
    assert manifest["repo_id"] == "repo-123"
    assert len(manifest["sources"]) == 21
    assert [len(batch) for _, batch in client.added_batches] == [20, 1]
    assert "XF_CHATDOC_REPO_ID=repo-123" in env_file.read_text()
    assert "XF_CHATDOC_REPO_ID=old-repo" not in env_file.read_text()


@pytest.mark.asyncio
async def test_run_ingest_does_not_publish_or_switch_when_vectoring_fails(tmp_path):
    class FailingChatDoc(FakeChatDoc):
        async def wait_until_vectored(self, file_ids, **kwargs):
            raise RuntimeError("vectoring failed")

    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "doc.md").write_text("document")
    artifact = tmp_path / "base.json"
    env_file = tmp_path / ".env"
    env_file.write_text("XF_CHATDOC_REPO_ID=old-repo\n")

    with pytest.raises(RuntimeError, match="vectoring failed"):
        await run_ingest(
            client=FailingChatDoc(),
            source_root=root,
            artifact_path=artifact,
            env_file=env_file,
            repo_name="failed-repo",
        )

    assert not artifact.exists()
    assert env_file.read_text() == "XF_CHATDOC_REPO_ID=old-repo\n"
