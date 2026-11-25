import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request

from common.storage import storage_exists, storage_open
from file.services import UploadFile
from file.utils.preview import SIZE_PREVIEW, SIZE_THUMB, ensure_image_cache
from file.utils.upload_store import UploadError, check_upload_limits, invalidate_upload_stats_cache, store_upload_file

IMAGE_MAX_BYTES = 10 * 1024 * 1024
VIDEO_MAX_BYTES = 30 * 1024 * 1024
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_VIDEO_EXTS = {".mp4", ".webm"}
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_SIZE = 65536


def sniff_media_kind(uploaded: Any, filename: str) -> tuple[str, str]:
    """Validate raster image or mp4/webm video via magic bytes + extension."""
    ext = Path(filename or "").suffix.lower()
    pos = uploaded.tell() if hasattr(uploaded, "tell") else 0
    header = uploaded.read(16)
    if hasattr(uploaded, "seek"):
        uploaded.seek(pos)
    if ext in ALLOWED_IMAGE_EXTS:
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "IMAGE", "image/png"
        if header.startswith(b"\xff\xd8\xff"):
            return "IMAGE", "image/jpeg"
        if header[:6] in (b"GIF87a", b"GIF89a"):
            return "IMAGE", "image/gif"
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return "IMAGE", "image/webp"
        raise ValidationError({"file": "图片文件内容与扩展名不匹配"})
    if ext in ALLOWED_VIDEO_EXTS:
        if ext == ".mp4" and len(header) >= 8 and header[4:8] == b"ftyp":
            return "VIDEO", "video/mp4"
        if ext == ".webm" and header.startswith(b"\x1a\x45\xdf\xa3"):
            return "VIDEO", "video/webm"
        raise ValidationError({"file": "视频文件内容与扩展名不匹配"})
    raise ValidationError({"file": "仅支持 JPG/PNG/WEBP/GIF 图片或 MP4/WebM 视频"})


def upload_ticket_media(user: Any, uploaded: Any, *, allow_video: bool) -> dict[str, Any]:
    if uploaded is None:
        raise ValidationError({"file": "请选择要上传的文件"})
    filename = str(getattr(uploaded, "name", "") or "file")
    kind, safe_mime = sniff_media_kind(uploaded, filename)
    if kind == "VIDEO" and not allow_video:
        raise ValidationError({"file": "建单仅支持上传图片（JPG/PNG/WEBP/GIF）"})
    size = int(getattr(uploaded, "size", 0) or 0)
    max_bytes = VIDEO_MAX_BYTES if kind == "VIDEO" else IMAGE_MAX_BYTES
    if size <= 0 or size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValidationError({"file": f"文件大小须在 1 字节至 {limit_mb} MB 之间"})
    try:
        check_upload_limits(user, [uploaded])
        record, _ = store_upload_file(user, uploaded, is_tmp=True)
        invalidate_upload_stats_cache(user.pk)
    except UploadError as exc:
        raise ValidationError({"file": str(exc)}) from exc
    if record.mime_type != safe_mime:
        record.mime_type = safe_mime
        record.save(update_fields=["mime_type", "updated_time"])
    return {
        "file_pk": str(record.pk),
        "kind": kind,
        "filename": record.filename,
        "filesize": record.filesize,
        "mime_type": safe_mime,
    }


def resolve_owned_media(user: Any, file_pk: int | str | UUID, *, expected_kind: str) -> UploadFile:
    upload = UploadFile.objects.filter(pk=file_pk, is_upload=True, creator_id=user.pk).first()
    if upload is None:
        raise ValidationError({"file_pk": "附件不存在或无权使用"})
    mime = str(upload.mime_type or "").lower()
    if expected_kind == "IMAGE" and not mime.startswith("image/"):
        raise ValidationError({"file_pk": "附件类型必须是图片"})
    if expected_kind == "VIDEO" and not mime.startswith("video/"):
        raise ValidationError({"file_pk": "附件类型必须是视频"})
    return upload


def mark_media_permanent(uploads: Iterable[UploadFile]) -> None:
    for upload in uploads:
        if upload.is_tmp:
            upload.is_tmp = False
            upload.save(update_fields=["is_tmp", "updated_time"])


def _iter_range(file_obj: Any, start: int, length: int) -> Iterator[bytes]:
    try:
        file_obj.seek(start)
        remaining = length
        while remaining > 0:
            chunk = file_obj.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        file_obj.close()


def _video_response(upload: UploadFile, request: Request, content_type: str) -> HttpResponse | StreamingHttpResponse:
    total_size = int(upload.filesize or 0)
    range_header = str(request.META.get("HTTP_RANGE", "") or "").strip()
    if range_header and total_size > 0:
        matched = RANGE_RE.match(range_header)
        if not matched:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{total_size}"
            return response
        raw_start, raw_end = matched.groups()
        if not raw_start and not raw_end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{total_size}"
            return response
        if raw_start:
            start = int(raw_start)
            end = int(raw_end) if raw_end else total_size - 1
        else:
            suffix = int(raw_end)
            start = max(0, total_size - suffix)
            end = total_size - 1
        if start >= total_size or end < start:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{total_size}"
            return response
        end = min(end, total_size - 1)
        length = end - start + 1
        stream = storage_open(upload.filepath.name, "rb")
        resp = StreamingHttpResponse(_iter_range(stream, start, length), status=206, content_type=content_type)
        resp["Content-Range"] = f"bytes {start}-{end}/{total_size}"
        resp["Content-Length"] = str(length)
        resp["Accept-Ranges"] = "bytes"
        resp["Cache-Control"] = "private, max-age=300"
        return resp
    stream = storage_open(upload.filepath.name, "rb")
    file_resp = FileResponse(stream, content_type=content_type)
    file_resp["Accept-Ranges"] = "bytes"
    if total_size > 0:
        file_resp["Content-Length"] = str(total_size)
    file_resp["Cache-Control"] = "private, max-age=300"
    return file_resp


def serve_media_response(upload: UploadFile | None, request: Request, *, kind: str, size: str = "") -> Any:
    if upload is None or not upload.filepath or not storage_exists(upload.filepath.name):
        raise NotFound("附件文件不存在")
    if kind == "IMAGE":
        if size in (SIZE_THUMB, SIZE_PREVIEW):
            cached_path = ensure_image_cache(upload, size)
            if cached_path:
                cached_file = Path(cached_path)
                if cached_file.is_file():
                    resp = FileResponse(cached_file.open("rb"), content_type="image/jpeg")
                    resp["Cache-Control"] = "private, max-age=300"
                    return resp
        mime = str(upload.mime_type or "image/png").split(";")[0].strip().lower()
        if not mime.startswith("image/") or "svg" in mime:
            mime = "application/octet-stream"
        resp = FileResponse(storage_open(upload.filepath.name, "rb"), content_type=mime)
        resp["Cache-Control"] = "private, max-age=300"
        resp["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(upload.filename)}"
        return resp
    mime = str(upload.mime_type or "video/mp4").split(";")[0].strip().lower()
    if mime not in ("video/mp4", "video/webm"):
        raise NotFound("不支持的视频格式")
    return _video_response(upload, request, mime)
