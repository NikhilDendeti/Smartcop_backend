"""Where evidence files live. The database holds only metadata; the bytes are in a backend chosen
by EVIDENCE_STORAGE: local disk for development, S3-compatible object storage for production."""

import os
import tempfile
from importlib import import_module
from pathlib import Path

from django.conf import settings


class StorageBackend:
    def presigned_upload(self, key, content_type, size_bytes, expires=900):
        """A URL the client can send the file to directly, or None if uploads go through the API."""
        return None

    def presigned_download(self, key, filename, content_type, expires=300):
        """A short-lived download URL, or None if downloads are streamed through the API."""
        return None

    def save(self, key, chunks):
        raise NotImplementedError

    def open(self, key):
        raise NotImplementedError

    def size(self, key):
        raise NotImplementedError

    def delete(self, key):
        raise NotImplementedError


class LocalFileStorage(StorageBackend):
    def __init__(self):
        self.root = Path(settings.EVIDENCE_ROOT).resolve()

    def _path(self, key):
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Storage key escapes the storage root.")
        return path

    def save(self, key, chunks):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file first so a half-sent upload never looks like a finished one.
        handle, temp_name = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as temp:
                for chunk in chunks:
                    temp.write(chunk)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def open(self, key):
        return open(self._path(key), "rb")

    def size(self, key):
        path = self._path(key)
        return path.stat().st_size if path.exists() else None

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)


class S3Storage(StorageBackend):
    """S3 or any S3-compatible service. Clients upload and download straight to the bucket with
    short-lived signed URLs, so large files never pass through the API servers."""

    def __init__(self):
        import boto3

        self.bucket = settings.EVIDENCE_S3_BUCKET
        self.client = boto3.client(
            "s3",
            region_name=settings.EVIDENCE_S3_REGION or None,
            endpoint_url=settings.EVIDENCE_S3_ENDPOINT_URL or None,
        )

    def presigned_upload(self, key, content_type, size_bytes, expires=900):
        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type, "ContentLength": size_bytes},
            ExpiresIn=expires,
        )
        return {"method": "PUT", "url": url, "headers": {"Content-Type": content_type}, "expires_in": expires}

    def presigned_download(self, key, filename, content_type, expires=300):
        safe_name = filename.replace('"', "")
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
            },
            ExpiresIn=expires,
        )

    def open(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]

    def size(self, key):
        from botocore.exceptions import ClientError

        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except ClientError as error:
            if error.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def save(self, key, chunks):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=b"".join(chunks))

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


def get_storage() -> StorageBackend:
    module_path, class_name = settings.EVIDENCE_STORAGE.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)()
