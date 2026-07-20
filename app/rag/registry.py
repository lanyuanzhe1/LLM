from pathlib import Path

from app.ingest.scanner import validate_project_id
from app.rag.vector_store import VectorStore, VectorStoreNotReady


class VectorStoreRegistry:
    def __init__(self, root_dir: Path) -> None:
        self._root = Path(root_dir)
        self._base: VectorStore | None = None
        self._base_loaded = False
        self._projects: dict[str, VectorStore | None] = {}

    def get_base(self) -> VectorStore | None:
        if not self._base_loaded:
            self._base = self._load_store(self._root / "base")
            self._base_loaded = True
        return self._base

    def get_project(self, project_id: str) -> VectorStore | None:
        project_id = validate_project_id(project_id)
        if project_id not in self._projects:
            store = self._load_store(self._root / "projects" / project_id)
            self._projects[project_id] = store
        return self._projects[project_id]

    def reload(self) -> None:
        self._base = None
        self._base_loaded = False
        self._projects.clear()

    @staticmethod
    def _load_store(directory: Path) -> VectorStore | None:
        try:
            return VectorStore.load(directory)
        except VectorStoreNotReady:
            return None
