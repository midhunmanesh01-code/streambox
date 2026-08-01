from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
import shutil
from pathlib import Path

from .config import LOCAL_STORAGE_DIR


class StorageBackend(ABC):
    @abstractmethod
    def write_stream(self, destination_key: str, source_stream, max_bytes: int | None = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def read_path(self, storage_key: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def delete(self, storage_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def path_for_key(self, storage_key: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def copy_path(self, source_path: Path, destination_key: str) -> int:
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    def __init__(self, root_dir: Path | str = LOCAL_STORAGE_DIR):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, storage_key: str) -> Path:
        path = self.root_dir / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def path_for_key(self, storage_key: str) -> Path:
        return self._resolve(storage_key)

    def write_stream(self, destination_key: str, source_stream, max_bytes: int | None = None) -> int:
        destination = self._resolve(destination_key)
        written = 0
        with destination.open('wb') as target:
            while True:
                chunk = source_stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    target.close()
                    destination.unlink(missing_ok=True)
                    raise ValueError('Upload exceeds the configured maximum size.')
                target.write(chunk)
        return written

    def read_path(self, storage_key: str) -> Path:
        path = self._resolve(storage_key)
        if not path.exists():
            raise FileNotFoundError(storage_key)
        return path

    def copy_path(self, source_path: Path, destination_key: str) -> int:
        destination = self._resolve(destination_key)
        shutil.copyfile(source_path, destination)
        return destination.stat().st_size

    def delete(self, storage_key: str) -> None:
        path = self.root_dir / storage_key
        if path.exists():
            path.unlink()

    def exists(self, storage_key: str) -> bool:
        return (self.root_dir / storage_key).exists()


def get_storage_backend() -> StorageBackend:
    return LocalStorageBackend()
