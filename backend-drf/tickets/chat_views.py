from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.urls.converters import UUIDConverter
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request

from common.core.response import ApiResponse
from tickets import chat_services
from tickets.media import serve_media_response, upload_ticket_media
from tickets.models import TicketAttachment, TicketChatMessage


class MediaUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class ChatMessageInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("TEXT", "IMAGE", "VIDEO"), default="TEXT")
    content = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    file_pk = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    client_msg_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


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

    @extend_schema(request=MediaUploadSerializer)
    @action(
        detail=False,
        methods=["post"],
        url_path="attachments/upload",
        parser_classes=[MultiPartParser],
        filterset_class=None,
    )
    def upload_attachment(self, request: Request) -> ApiResponse:
        """上传工单图片"""
        data = upload_ticket_media(self.actor, request.FILES.get("file"), allow_video=False)
        return ApiResponse(data=data, status=201)

    @extend_schema(parameters=[OpenApiParameter("size", str, description="图片尺寸：thumb 或 preview")])
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
        parameters=[
            OpenApiParameter("limit", int),
            OpenApiParameter("before_id", UUID),
            OpenApiParameter("after_id", UUID),
        ],
    )
    @action(detail=True, methods=["get"], url_path="chat/messages", filterset_class=None)
    def chat_messages(self, request: Request, pk: UUID) -> ApiResponse:
        """查询排查消息"""
        ticket = self.get_object()
        raw_limit = request.query_params.get("limit", "50")
        limit = int(raw_limit) if str(raw_limit).isdigit() else 50
        before_raw = str(request.query_params.get("before_id", "") or "").strip()
        after_raw = str(request.query_params.get("after_id", "") or "").strip()
        before_id = UUID(before_raw) if before_raw else None
        after_id = UUID(after_raw) if after_raw else None
        data = chat_services.list_chat_messages(
            ticket, self.access, limit=limit, before_id=before_id, after_id=after_id
        )
        return ApiResponse(data=data)

    @extend_schema(request=ChatMessageInputSerializer)
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

    @extend_schema(request=MediaUploadSerializer)
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
        if not chat_services.chat_state(ticket, self.access)["can_send"]:
            raise PermissionDenied("当前工单会话不可上传媒体")
        data = upload_ticket_media(self.actor, request.FILES.get("file"), allow_video=True)
        return ApiResponse(data=data, status=201)

    @action(detail=True, methods=["post"], url_path="chat/read", filterset_class=None)
    def chat_read(self, request: Request, pk: UUID) -> ApiResponse:
        """标记会话已读"""
        ticket = self.get_object()
        chat_services.mark_chat_read(ticket, self.actor)
        return ApiResponse()

    @extend_schema(parameters=[OpenApiParameter("size", str, description="图片尺寸：thumb 或 preview")])
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
