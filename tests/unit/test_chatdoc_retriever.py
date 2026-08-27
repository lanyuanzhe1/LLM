import json
from pathlib import Path

import pytest

from app.clients.iflytek_chatdoc import ChatDocSearchHit
from app.rag.chatdoc_retriever import ChatDocRetriever, load_chatdoc_manifest
from app.schemas.tools import RetrieveRequest


def _write_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backend": "iflytek_chatdoc",
                "repo_id": "repo-123",
                "sources": {
                    "政策文件类/粮食安全法.pdf": {
                        "sha256": "a" * 64,
                        "source_type": "政策文件类",
                        "uploads": [
                            {
                                "file_id": "file-law",
                                "upload_name": "law.pdf",
                                "status": "vectored",
                            }
                        ],
                    },
                    "其他论文/低温储粮.pdf": {
                        "sha256": "b" * 64,
                        "source_type": "其他论文",
                        "uploads": [
                            {
                                "file_id": "file-paper",
                                "upload_name": "paper.pdf",
                                "status": "vectored",
                            }
                        ],
                    },
                },
                "skipped_sources": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class FakeChatDoc:
    def __init__(self):
        self.calls = []

    async def search(self, *, repo_id, query, top_n):
        self.calls.append((repo_id, query, top_n))
        return [
            ChatDocSearchHit(
                content="政府粮食储备实行专仓储存。",
                score=83.5,
                file_id="file-law",
                index=7,
                retrieval_type="vector",
            ),
            ChatDocSearchHit(
                content="低温能够抑制粮食呼吸。",
                score=0.72,
                file_id="file-paper",
                index=3,
                retrieval_type="vector",
            ),
        ]


def test_load_manifest_maps_each_remote_file_to_original_source(tmp_path):
    path = tmp_path / "base.json"
    _write_manifest(path)

    manifest = load_chatdoc_manifest(path)

    assert manifest.repo_id == "repo-123"
    assert manifest.files["file-law"].source == "政策文件类/粮食安全法.pdf"
    assert manifest.files["file-paper"].checksum == "b" * 64


@pytest.mark.asyncio
async def test_retriever_normalizes_scores_builds_evidence_and_caches_it(tmp_path):
    path = tmp_path / "base.json"
    _write_manifest(path)
    client = FakeChatDoc()
    retriever = ChatDocRetriever(
        client=client,
        manifest=load_chatdoc_manifest(path),
        min_score=0.35,
    )

    response = await retriever.retrieve(
        RetrieveRequest(request_id="req", query="政府储备", top_k=2)
    )

    assert client.calls == [("repo-123", "政府储备", 2)]
    assert [item.score for item in response.evidences] == [0.835, 0.72]
    assert response.evidences[0].source == "政策文件类/粮食安全法.pdf"
    assert response.evidences[0].text == "政府粮食储备实行专仓储存。"
    assert response.quality.sufficient is True
    assert retriever.get_evidence(response.evidences[0].evidence_id) == response.evidences[0]


@pytest.mark.asyncio
async def test_filters_request_more_candidates_and_apply_before_top_k(tmp_path):
    path = tmp_path / "base.json"
    _write_manifest(path)
    client = FakeChatDoc()
    retriever = ChatDocRetriever(
        client=client,
        manifest=load_chatdoc_manifest(path),
        min_score=0.35,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="储粮",
            top_k=1,
            filters={"source_type": "其他论文"},
        )
    )

    assert client.calls == [("repo-123", "储粮", 20)]
    assert [item.source for item in response.evidences] == ["其他论文/低温储粮.pdf"]


@pytest.mark.asyncio
async def test_unknown_file_id_is_not_exposed_as_untraceable_evidence(tmp_path):
    class UnknownFileClient(FakeChatDoc):
        async def search(self, **kwargs):
            return [
                ChatDocSearchHit(
                    content="orphan",
                    score=99,
                    file_id="unknown",
                    index=1,
                    retrieval_type="vector",
                )
            ]

    path = tmp_path / "base.json"
    _write_manifest(path)
    retriever = ChatDocRetriever(
        client=UnknownFileClient(),
        manifest=load_chatdoc_manifest(path),
        min_score=0.35,
    )

    response = await retriever.retrieve(
        RetrieveRequest(request_id="req", query="query", top_k=1)
    )

    assert response.evidences == []
    assert response.quality.sufficient is False
