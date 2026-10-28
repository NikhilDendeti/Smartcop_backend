"""Evidence upload and download.

Flow: the client announces a file (name, type, size, SHA-256) and gets an upload target; it sends
the bytes there; it then calls "complete", where the server reads the stored file back, checks the
size and checksum, and has it virus-scanned. A file can be downloaded only after that succeeds, and
only by people who may see the complaint."""

import hashlib
import re
import uuid

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from core import audit
from core.scanning import get_scanner
from core.storage import get_storage
from users.access import actor_role, complaints_for
from users.models import EvidenceFile
from users.permissions import IsEvidenceReader, IsEvidenceUploader

# Declared content type -> evidence category. Anything else is refused.
CONTENT_TYPES = {
    "image/jpeg": "image", "image/png": "image", "image/webp": "image", "image/heic": "image",
    "video/mp4": "video", "video/quicktime": "video", "video/webm": "video",
    "audio/mpeg": "audio", "audio/wav": "audio", "audio/x-wav": "audio", "audio/mp4": "audio",
    "audio/webm": "audio", "audio/ogg": "audio",
    "application/pdf": "document",
}
UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")


class Conflict(APIException):
    status_code = 409
    default_code = "conflict"


class EvidenceInitSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=150)
    size_bytes = serializers.IntegerField(min_value=1)
    sha256 = serializers.RegexField(r"^[0-9a-fA-F]{64}$", error_messages={"invalid": "Send the file's SHA-256 as 64 hex characters."})

    def validate_content_type(self, value):
        # Browsers label recordings like "video/webm;codecs=vp9,opus"; only the base type matters.
        base = value.split(";")[0].strip().lower()
        if base not in CONTENT_TYPES:
            raise serializers.ValidationError(f"Files of type '{base}' are not accepted.")
        return base

    def validate(self, attrs):
        category = CONTENT_TYPES[attrs["content_type"]]
        limit = settings.EVIDENCE_MAX_BYTES[category]
        if attrs["size_bytes"] > limit:
            raise serializers.ValidationError({"size_bytes": f"{category.title()} files can be at most {limit // (1024 * 1024)} MB."})
        attrs["file_type"] = category
        attrs["filename"] = UNSAFE_NAME.sub("_", attrs["filename"]).strip(". ") or "file"
        attrs["sha256"] = attrs["sha256"].lower()
        return attrs


def _row(record):
    return {
        "file_id": str(record.pk),
        "filename": record.original_filename,
        "type": record.file_type,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "uploaded": record.verified_at is not None,
        "scan_status": record.scan_status,
        "uploaded_at": record.uploaded_at.isoformat(),
    }


def _visible_file(user, file_id):
    record = EvidenceFile.objects.filter(
        pk=file_id, complaint_id__in=complaints_for(user).values("pk")
    ).select_related("complaint").first()
    if record is None:
        raise NotFound("File not found.")
    return record


def _own_pending_file(user, file_id):
    record = _visible_file(user, file_id)
    if record.uploaded_by_id != user.pk:
        raise NotFound("File not found.")
    return record


@extend_schema(request=EvidenceInitSerializer, tags=["evidence"])
@api_view(["GET", "POST"])
@permission_classes([IsEvidenceReader])
def complaint_evidence(request, complaint_id):
    complaint = complaints_for(request.user).filter(pk=complaint_id).first()
    if complaint is None:
        raise NotFound("Complaint not found.")

    if request.method == "GET":
        return Response([_row(item) for item in complaint.evidence_files.order_by("uploaded_at")])

    if actor_role(request.user) not in IsEvidenceUploader.allowed_roles:
        raise PermissionDenied("Your role cannot add evidence.")
    serializer = EvidenceInitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if complaint.evidence_files.count() >= settings.EVIDENCE_MAX_FILES_PER_COMPLAINT:
        raise ValidationError("This complaint already has the maximum number of evidence files.")

    file_id = uuid.uuid4()
    record = EvidenceFile.objects.create(
        file_id=file_id,
        complaint=complaint,
        uploaded_by=request.user,
        file_type=data["file_type"],
        storage_key=f"evidence/{complaint.pk}/{file_id}",
        original_filename=data["filename"],
        content_type=data["content_type"],
        size_bytes=data["size_bytes"],
        sha256=data["sha256"],
    )
    target = get_storage().presigned_upload(record.storage_key, record.content_type, record.size_bytes)
    audit.record(request, "evidence_init", "complaint", complaint.pk, metadata={"file": str(file_id)})
    return Response(
        {
            **_row(record),
            "upload": target or {"method": "PUT", "url": f"/api/v1/evidence-files/{file_id}/content/",
                                 "headers": {"Content-Type": "application/octet-stream"}},
        },
        status=201,
    )


@extend_schema(request={"application/octet-stream": OpenApiTypes.BINARY}, tags=["evidence"])
@api_view(["PUT"])
@permission_classes([IsEvidenceUploader])
@parser_classes([])
def evidence_content(request, file_id):
    """Receives the bytes when storage is local. With S3 the client uploads straight to the bucket."""
    record = _own_pending_file(request.user, file_id)
    storage = get_storage()
    if storage.presigned_upload(record.storage_key, record.content_type, record.size_bytes) is not None:
        raise ValidationError("Upload the file directly to the URL you were given.")
    if record.verified_at:
        raise Conflict("This file was already uploaded.")

    try:
        length = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length != record.size_bytes:
        raise ValidationError(f"The upload must be exactly {record.size_bytes} bytes.")

    raw = request._request

    def chunks():
        remaining = length
        while remaining > 0:
            part = raw.read(min(64 * 1024, remaining))
            if not part:
                break
            remaining -= len(part)
            yield part

    storage.save(record.storage_key, chunks())
    return Response(status=204)


@extend_schema(request=None, tags=["evidence"])
@api_view(["POST"])
@permission_classes([IsEvidenceUploader])
def evidence_complete(request, file_id):
    record = _own_pending_file(request.user, file_id)
    if record.verified_at:
        return Response(_row(record))

    storage = get_storage()
    actual_size = storage.size(record.storage_key)
    if actual_size is None:
        raise Conflict("No file has been uploaded yet.")

    digest = hashlib.sha256()
    stream = storage.open(record.storage_key)
    try:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    finally:
        stream.close()

    if actual_size != record.size_bytes or digest.hexdigest() != record.sha256:
        storage.delete(record.storage_key)
        record.delete()
        raise ValidationError("The uploaded file does not match its declared size and checksum. Please upload it again.")

    record.verified_at = timezone.now()
    try:
        record.scan_status = get_scanner().scan(lambda: storage.open(record.storage_key))
    except Exception:
        record.scan_status = "failed"
    record.save(update_fields=["verified_at", "scan_status"])
    audit.record(request, "evidence_uploaded", "complaint", record.complaint_id,
                 metadata={"file": str(record.pk), "scan": record.scan_status})
    return Response(_row(record))


@extend_schema(tags=["evidence"])
@api_view(["GET"])
@permission_classes([IsEvidenceReader])
def evidence_download(request, file_id):
    record = _visible_file(request.user, file_id)
    if record.verified_at is None:
        raise Conflict("This file has not finished uploading.")
    if record.scan_status == "infected":
        raise PermissionDenied("This file failed the virus scan and cannot be downloaded.")
    if record.scan_status != "clean" and not settings.EVIDENCE_ALLOW_UNSCANNED:
        raise Conflict("This file has not passed a virus scan yet.")

    audit.record(request, "evidence_download", "complaint", record.complaint_id, metadata={"file": str(record.pk)})
    storage = get_storage()
    url = storage.presigned_download(record.storage_key, record.original_filename, record.content_type)
    if url:
        return Response({"url": url, "expires_in": 300})

    response = FileResponse(
        storage.open(record.storage_key), as_attachment=True, filename=record.original_filename,
        content_type=record.content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
