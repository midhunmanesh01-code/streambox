from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from .config import (
    B2_APPLICATION_KEY,
    B2_BUCKET_NAME,
    B2_ENDPOINT,
    B2_KEY_ID,
    B2_REGION,
    LOCAL_STORAGE_DIR,
    STORAGE_BACKEND,
    TEMP_DIR,
)


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

    def presigned_get_url(self, storage_key: str, expires_in: int) -> str:
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
        if source_path.resolve() == destination.resolve():
            return destination.stat().st_size
        shutil.copyfile(source_path, destination)
        return destination.stat().st_size

    def delete(self, storage_key: str) -> None:
        path = self.root_dir / storage_key
        if path.exists():
            path.unlink()

    def exists(self, storage_key: str) -> bool:
        return (self.root_dir / storage_key).exists()

    def presigned_get_url(self, storage_key: str, expires_in: int) -> str:
        raise NotImplementedError('Local storage does not provide presigned URLs.')


class BackblazeB2StorageBackend(StorageBackend):
    def __init__(self):
        missing = [
            name
            for name, value in (
                ('B2_KEY_ID', B2_KEY_ID),
                ('B2_APPLICATION_KEY', B2_APPLICATION_KEY),
                ('B2_BUCKET_NAME', B2_BUCKET_NAME),
                ('B2_ENDPOINT', B2_ENDPOINT),
                ('B2_REGION', B2_REGION),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f'Missing Backblaze B2 configuration: {", ".join(missing)}')

        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
        except ImportError as exc:
            raise RuntimeError('Backblaze B2 storage requires boto3. Install the backend requirements first.') from exc

        self._bucket_name = B2_BUCKET_NAME
        self._client_error = ClientError
        self._working_dir = TEMP_DIR / 'b2-storage'
        self._working_dir.mkdir(parents=True, exist_ok=True)
        endpoint_url = B2_ENDPOINT if B2_ENDPOINT.startswith(('http://', 'https://')) else f'https://{B2_ENDPOINT}'
        self._client = boto3.client(
            's3',
            aws_access_key_id=B2_KEY_ID,
            aws_secret_access_key=B2_APPLICATION_KEY,
            region_name=B2_REGION,
            endpoint_url=endpoint_url,
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
        )

    def _resolve(self, storage_key: str) -> Path:
        path = self._working_dir / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _download(self, storage_key: str, destination: Path) -> None:
        try:
            self._client.download_file(self._bucket_name, storage_key, str(destination))
        except self._client_error as exc:
            error_code = str(exc.response.get('Error', {}).get('Code', ''))
            if error_code in {'404', 'NoSuchKey', 'NotFound', 'NoSuchBucket'}:
                destination.unlink(missing_ok=True)
                raise FileNotFoundError(storage_key) from exc
            raise

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

        self._client.upload_file(str(destination), self._bucket_name, destination_key)
        return written

    def read_path(self, storage_key: str) -> Path:
        path = self._resolve(storage_key)
        if not path.exists():
            self._download(storage_key, path)
        return path

    def copy_path(self, source_path: Path, destination_key: str) -> int:
        self._client.upload_file(str(source_path), self._bucket_name, destination_key)
        return source_path.stat().st_size

    def delete(self, storage_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket_name, Key=storage_key)
        self._resolve(storage_key).unlink(missing_ok=True)

    def exists(self, storage_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket_name, Key=storage_key)
            return True
        except self._client_error as exc:
            error_code = str(exc.response.get('Error', {}).get('Code', ''))
            if error_code in {'404', 'NoSuchKey', 'NotFound', 'NoSuchBucket'}:
                return False
            raise

    def presigned_get_url(self, storage_key: str, expires_in: int) -> str:
        return self._client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self._bucket_name, 'Key': storage_key},
            ExpiresIn=expires_in,
        )


def get_storage_backend() -> StorageBackend:
    if STORAGE_BACKEND == 'local':
        return LocalStorageBackend()
    if STORAGE_BACKEND == 'b2':
        return BackblazeB2StorageBackend()
    raise ValueError(f'Unsupported storage backend: {STORAGE_BACKEND}')
