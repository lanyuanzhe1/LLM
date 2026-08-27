"""Upload the base knowledge corpus to iFlytek ChatDoc."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.clients.iflytek_chatdoc import IflytekChatDocClient
from app.ingest.chatdoc_upload import run_ingest


class ChatDocIngestSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    xf_app_id: str
    xf_embedding_api_secret: SecretStr


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the managed iFlytek ChatDoc base knowledge repository"
    )
    parser.add_argument("--source", type=Path, default=Path("knowledge"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("artifacts/chatdoc/base.json"),
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--repo-name",
        default=f"粮食储藏知识库-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    )
    args = parser.parse_args()

    settings = ChatDocIngestSettings()
    client = IflytekChatDocClient(
        app_id=settings.xf_app_id,
        api_secret=settings.xf_embedding_api_secret.get_secret_value(),
        timeout_seconds=120.0,
    )

    async def execute():
        try:
            return await run_ingest(
                client=client,
                source_root=args.source,
                artifact_path=args.manifest,
                env_file=args.env_file,
                repo_name=args.repo_name,
                progress=print,
            )
        finally:
            await client.close()

    result = asyncio.run(execute())
    print(
        f"ChatDoc ready: repo={result.repo_id}, uploaded={result.uploaded_files}, "
        f"skipped={result.skipped_files}"
    )


if __name__ == "__main__":
    main()
