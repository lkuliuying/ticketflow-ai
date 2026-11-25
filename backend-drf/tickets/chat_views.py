from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.urls.converters import UUIDConverter
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request

from common.core.response import ApiResponse
from tickets import chat_services
from tickets.api_schema import TicketChatStateSerializer, envelope, ticket_error_result
from tickets.cache import check_rate
from tickets.media import serve_media_response, upload_ticket_media
from tickets.models import TicketAttachment, TicketChatMessage
from tickets.policy import has_permission
from tickets.serializers import TicketMediaIdField


@extend_schema_field(OpenApiTypes.BINARY)
class TicketMediaFileField(serializers.FileField):
    pass


class MediaUploadSerializer(serializers.Serializer):
    file = TicketMediaFileField()


class ChatMessageInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("TEXT", "IMAGE", "VIDEO"), default="TEXT")
    content = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    file_pk = TicketMediaIdField(required=False, allow_null=True)
    client_msg_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class ChatQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)
    before_id = serializers.UUIDField(required=False)
    after_id = serializers.UUIDField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "before_id" in attrs and "after_id" in attrs:
            raise serializers.ValidationError("before_id 和 after_id 只能选一个")
        return attrs


class MediaUploadResultSerializer(serializers.Serializer):
    file_pk = TicketMediaIdField()
    kind = serializers.ChoiceField(choices=("IMAGE", "VIDEO"))
    filename = serializers.CharField()
    filesize = serializers.IntegerField(min_value=1)
    mime_type = serializers.CharField()


class ChatMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    ticket_id = serializers.UUIDField()
    sender_id = serializers.IntegerField(allow_null=True)
    sender_name = serializers.CharField()
    kind = serializers.ChoiceField(choices=TicketChatMessage.Kind.choices)
    content = serializers.CharField(allow_blank=True)
    media_meta = serializers.DictField()
    media_expired = serializers.BooleanField()
    file_url = serializers.CharField(allow_null=True)
    thumb_url = serializers.CharField(allow_null=True)
    client_msg_id = serializers.CharField(allow_blank=True)
    created_time = serializers.DateTimeField()


class ChatPageSerializer(serializers.Serializer):
    results = ChatMessageSerializer(many=True)
    has_more = serializers.BooleanField()
    chat_state = TicketChatStateSerializer()


media_upload_result = envelope("TicketMediaUploadResult", MediaUploadResultSerializer())
chat_message_result = envelope("TicketChatMessageResult", ChatMessageSerializer())
chat_page_result = envelope("TicketChatPageResult", ChatPageSerializer())
chat_read_result = envelope("TicketChatReadResult")
media_errors = {400: ticket_error_result, 429: ticket_error_result, 503: ticket_error_result}
image_responses = {
    (200, mime): OpenApiTypes.BINARY
    for mime in ("image/jpeg", "image/png", "image/webp", "image/gif", "application/octet-stream")
}
video_responses = {(status, mime): OpenApiTypes.BINARY for status in (200, 206) for mime in ("video/mp4", "video/webm")}


class TicketMediaChatMixin:
    """工单附件与实时排查会话动作混入。"""

    if TYPE_CHECKING:

        def get_object(self) -> Any: ...

        def get_queryset(self) -> Any: ...

        def filter_queryset(self, queryset: Any) -> Any: ...

        @property
        def actor(self) -> Any: ...

        @property
        def access(self) -> Any: ...

    @extend_schema(request=MediaUploadSerializer, responses={201: media_upload_result, **media_errors})
    @action(
        detail=False,
        methods=["post"],
        url_path="attachments/upload",
        parser_classes=[MultiPartParser],
        filterset_class=None,
    )
    def upload_attachment(self, request: Request) -> ApiResponse:
        """上传工单图片"""
        check_rate(self.actor.pk, "ticket-media-upload", 30)
        data = upload_ticket_media(self.actor, request.FILES.get("file"), allow_video=False)
        return ApiResponse(data=data, status=201)

    @extend_schema(
        parameters=[OpenApiParameter("size", str, description="图片尺寸：thumb 或 preview")],
        responses={**image_responses, 404: ticket_error_result},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path=rf"attachments/(?P<attachment_id>{UUIDConverter.regex})",
        filterset_class=None,
    )
    def attachment_file(self, request: Request, pk: UUID, attachment_id: UUID) -> Any:
        """读取工单图片"""
        ticket = self.get_object()
        attachment = TicketAttachment.objects.select_related("file").filter(pk=attachment_id, ticket=ticket).first()
        if attachment is None:
            raise NotFound("工单图片不存在")
        size = str(request.query_params.get("size", "") or "").strip().lower()
        return serve_media_response(attachment.file, request, kind="IMAGE", size=size)

    @extend_schema(
        parameters=[ChatQuerySerializer],
        responses={200: chat_page_result, 400: ticket_error_result, 404: ticket_error_result},
    )
    @action(detail=True, methods=["get"], url_path="chat/messages", filterset_class=None)
    def chat_messages(self, request: Request, pk: UUID) -> ApiResponse:
        """查询排查消息"""
        ticket = self.get_object()
        serializer = ChatQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = chat_services.list_chat_messages(
            ticket,
            self.access,
            can_send=has_permission(self.actor, chat_services.CHAT_SEND_PERMISSION),
            **serializer.validated_data,
        )
        return ApiResponse(data=data)

    @extend_schema(
        request=ChatMessageInputSerializer,
        responses={200: chat_message_result, 201: chat_message_result, 403: ticket_error_result, **media_errors},
    )
    @chat_messages.mapping.post
    def chat_send(self, request: Request, pk: UUID) -> ApiResponse:
        """发送排查消息"""
        serializer = ChatMessageInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scope = self.filter_queryset(self.get_queryset())
        msg, created = chat_services.send_chat_message(scope, pk, self.actor, self.access, **serializer.validated_data)
        return ApiResponse(
            data=chat_services.serialize_chat_message(msg, pk),
            status=201 if created else 200,
        )

    @extend_schema(
        request=MediaUploadSerializer, responses={201: media_upload_result, 403: ticket_error_result, **media_errors}
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="chat/upload",
        parser_classes=[MultiPartParser],
        filterset_class=None,
    )
    def chat_upload(self, request: Request, pk: UUID) -> ApiResponse:
        """上传排查媒体"""
        ticket = self.get_object()
        can_send = has_permission(self.actor, chat_services.CHAT_SEND_PERMISSION)
        if not chat_services.chat_state(ticket, self.access, can_send=can_send)["can_send"]:
            raise PermissionDenied("当前工单会话不可上传媒体")
        check_rate(self.actor.pk, "ticket-media-upload", 30)
        data = upload_ticket_media(self.actor, request.FILES.get("file"), allow_video=True)
        return ApiResponse(data=data, status=201)

    @extend_schema(request=None, responses=chat_read_result)
    @action(detail=True, methods=["post"], url_path="chat/read", filterset_class=None)
    def chat_read(self, request: Request, pk: UUID) -> ApiResponse:
        """标记会话已读"""
        ticket = self.get_object()
        chat_services.mark_chat_read(ticket, self.actor)
        return ApiResponse()

    @extend_schema(
        parameters=[
            OpenApiParameter("size", str, description="图片尺寸：thumb 或 preview"),
            OpenApiParameter("Range", str, OpenApiParameter.HEADER, description="视频的单字节范围"),
            OpenApiParameter("Content-Range", str, OpenApiParameter.HEADER, response=[206, 416]),
        ],
        responses={**image_responses, **video_responses, 404: ticket_error_result, 416: None},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path=rf"chat/messages/(?P<message_id>{UUIDConverter.regex})/file",
        filterset_class=None,
    )
    def chat_file(self, request: Request, pk: UUID, message_id: UUID) -> Any:
        """读取排查媒体"""
        ticket = self.get_object()
        msg = TicketChatMessage.objects.select_related("attachment").filter(pk=message_id, ticket=ticket).first()
        if msg is None or msg.media_expired or msg.attachment is None:
            raise NotFound("会话媒体不存在或已过期")
        size = str(request.query_params.get("size", "") or "").strip().lower()
        return serve_media_response(msg.attachment, request, kind=msg.kind, size=size)
