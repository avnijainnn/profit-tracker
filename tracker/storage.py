"""Private database-backed media storage for the single-owner deployment."""

from django.core.files.base import ContentFile
from django.core.files.storage import Storage

from .models import StoredUpload


class DatabaseStorage(Storage):
    def _save(self, name, content):
        StoredUpload.objects.create(path=name, data=b"".join(content.chunks()))
        return name

    def _open(self, name, mode="rb"):
        if mode not in ("r", "rb"):
            raise ValueError("Stored uploads are read-only after saving.")
        data = StoredUpload.objects.filter(path=name).values_list("data", flat=True).first()
        if data is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(data), name=name)

    def delete(self, name):
        if name:
            StoredUpload.objects.filter(path=name).delete()

    def exists(self, name):
        return StoredUpload.objects.filter(path=name).exists()

    def size(self, name):
        data = StoredUpload.objects.filter(path=name).values_list("data", flat=True).first()
        if data is None:
            raise FileNotFoundError(name)
        return len(data)
