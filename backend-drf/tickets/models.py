from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Upper

from common.core.models import DbAuditModel, DbBaseModel, DbUuidModel, SoftDeleteModel


class Category(models.TextChoices):
    ACCOUNT = "ACCOUNT", "账户"
    ACCESS = "ACCESS", "权限"
    NETWORK = "NETWORK", "网络"
    SERVICE = "SERVICE", "服务"
    OTHER = "OTHER", "其他"


class Priority(models.TextChoices):
    P0 = "P0", "P0"
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"


class CategoryRoute(models.Model):
    category = models.CharField("分类", max_length=12, choices=Category.choices, primary_key=True)
    skill_group = models.ForeignKey("identity.DeptInfo", on_delete=models.PROTECT, related_name="ticket_routes")


class Status(models.TextChoices):
    OPEN = "OPEN", "待处理"
    IN_PROGRESS = "IN_PROGRESS", "处理中"
    PENDING_VERIFY = "PENDING_VERIFY", "待验收"
    CLOSED = "CLOSED", "已关闭"
    REOPENED = "REOPENED", "已重开"


class Visibility(models.TextChoices):
    PUBLIC = "PUBLIC", "对外回复"
    INTERNAL = "INTERNAL", "内部备注"


class Ticket(DbAuditModel, DbUuidModel):
    number = models.CharField("工单号", max_length=35, unique=True)
    title = models.CharField("标题", max_length=200)
    description = models.TextField("工单描述")
    category = models.CharField("分类", max_length=12, choices=Category.choices)
    priority = models.CharField("优先级", max_length=2, choices=Priority.choices)
    status = models.CharField("状态", max_length=16, choices=Status.choices, default=Status.OPEN)
    submitter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_tickets")
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets"
    )
    department = models.ForeignKey("identity.DeptInfo", on_delete=models.PROTECT, related_name="tickets")
    sla_due_at = models.DateTimeField("SLA 截止时间")
    sla_cycle = models.PositiveIntegerField(default=1)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    ai_tags = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "工单"
        ordering = ("-created_time", "-id")
        indexes = [
            models.Index(fields=["status", "priority", "sla_due_at"], name="tf_status_priority_sla_idx"),
            models.Index(fields=["assignee", "status"], name="tf_assignee_status_idx"),
            models.Index(fields=["department", "status"], name="tf_dept_status_idx"),
            models.Index(fields=["submitter", "-created_time"], name="tf_submitter_created_idx"),
            models.Index(fields=["sla_due_at"], condition=models.Q(resolved_at__isnull=True), name="tf_active_sla_idx"),
            GinIndex(OpClass(Upper("title"), name="gin_trgm_ops"), name="tf_ticket_title_trgm_idx"),
            GinIndex(OpClass(Upper("number"), name="gin_trgm_ops"), name="tf_ticket_number_trgm_idx"),
        ]

    def __str__(self) -> str:
        return self.number


class TicketAssignment(DbUuidModel):
    class EndReason(models.TextChoices):
        REASSIGNED = "REASSIGNED", "改派"
        RETURNED = "RETURNED", "退回"
        DEACTIVATED = "DEACTIVATED", "处理人停用"
        CLOSED_OUT = "CLOSED_OUT", "工单关闭"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="assignments")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=12, choices=EndReason.choices, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ticket"], condition=models.Q(ended_at__isnull=True), name="tf_open_assignment_once"
            )
        ]
        indexes = [
            models.Index(fields=["ticket", "assignee"], name="tf_assignment_history_idx"),
            models.Index(fields=["assignee", "-started_at"], name="tf_assignment_latest_idx"),
        ]


class RatingTag(models.TextChoices):
    FAST = "FAST", "响应快"
    PROFESSIONAL = "PROFESSIONAL", "专业"
    FRIENDLY = "FRIENDLY", "态度好"
    CLEAR = "CLEAR", "沟通清楚"


class TicketRating(DbUuidModel):
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name="rating", verbose_name="工单")
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="given_ticket_ratings", verbose_name="评价人"
    )
    handler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_ticket_ratings",
        verbose_name="被评处理人",
    )
    resolved = models.BooleanField("是否解决")
    satisfaction = models.PositiveSmallIntegerField("满意度", validators=[MinValueValidator(1), MaxValueValidator(5)])
    handler_score = models.PositiveSmallIntegerField(
        "处理人评分", validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    tags = models.JSONField("标签", default=list, blank=True)
    comment = models.CharField("文字评价", max_length=500, null=True, blank=True)
    created_time = models.DateTimeField("评价时间", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "工单评价"
        ordering = ("-created_time", "-id")
        constraints = [
            models.CheckConstraint(condition=models.Q(satisfaction__range=(1, 5)), name="tf_rating_satisfaction_range"),
            models.CheckConstraint(
                condition=models.Q(handler_score__range=(1, 5)), name="tf_rating_handler_score_range"
            ),
        ]


class TicketLog(DbUuidModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="logs")
    action = models.CharField(max_length=20)
    from_status = models.CharField(max_length=16, choices=Status.choices, null=True, blank=True)
    to_status = models.CharField(max_length=16, choices=Status.choices)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    note = models.TextField(blank=True, default="")
    internal = models.BooleanField(default=False)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_time", "-id")
        indexes = [models.Index(fields=["ticket", "-created_time", "-id"], name="tf_log_timeline_idx")]


class TicketComment(DbUuidModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField()
    visibility = models.CharField(max_length=8, choices=Visibility.choices)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_time", "-id")
        indexes = [models.Index(fields=["ticket", "-created_time", "-id"], name="tf_comment_timeline_idx")]


class TicketCreateRequest(DbUuidModel):
    submitter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key_hash = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    # 创建事务持有键后填充工单，事务提交前外部无法看到空关联。
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, null=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["submitter", "key_hash"], name="tf_create_request_once"),
        ]


class TicketSlaAlert(DbUuidModel):
    class Kind(models.TextChoices):
        DUE_SOON = "DUE_SOON", "即将超时"
        OVERDUE = "OVERDUE", "已超时"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="sla_alerts")
    sla_cycle = models.PositiveIntegerField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    sla_due_at = models.DateTimeField()
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ticket", "sla_cycle", "kind"], name="tf_sla_alert_once"),
        ]


class AssistantSession(SoftDeleteModel, DbBaseModel, DbUuidModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assistant_sessions")
    title = models.CharField(max_length=200)
    ticket = models.OneToOneField(
        Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="assistant_session"
    )

    class Meta:
        verbose_name = "助手会话"
        ordering = ("-updated_time", "-id")
        indexes = [models.Index(fields=["user", "-updated_time", "-id"], name="tf_assistant_session_idx")]


class AssistantMessage(DbUuidModel):
    class Role(models.TextChoices):
        USER = "user", "提问"
        ASSISTANT = "assistant", "回答"

    class Status(models.TextChoices):
        COMPLETE = "complete", "完成"
        INTERRUPTED = "interrupted", "中断"
        FAILED = "failed", "失败"

    session = models.ForeignKey(AssistantSession, on_delete=models.CASCADE, related_name="messages")
    user_message = models.OneToOneField("self", on_delete=models.CASCADE, null=True, blank=True, related_name="answer")
    role = models.CharField(max_length=9, choices=Role.choices)
    content = models.TextField(blank=True)
    references = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=11, choices=Status.choices, default=Status.COMPLETE)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "助手消息"
        ordering = ("created_time", "id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role="user", user_message__isnull=True)
                | models.Q(role="assistant", user_message__isnull=False),
                name="tf_assistant_message_role",
            )
        ]
        indexes = [models.Index(fields=["session", "created_time", "id"], name="tf_assistant_message_idx")]


class AssistantFeedback(DbBaseModel, DbUuidModel):
    class Vote(models.TextChoices):
        UP = "up", "点赞"
        DOWN = "down", "点踩"

    class Reason(models.TextChoices):
        INACCURATE = "INACCURATE", "不准确"
        UNRESOLVED = "UNRESOLVED", "没解决"
        IRRELEVANT = "IRRELEVANT", "引用不相关"
        OTHER = "OTHER", "其他"

    message = models.OneToOneField(AssistantMessage, on_delete=models.CASCADE, related_name="feedback")
    vote = models.CharField(max_length=4, choices=Vote.choices)
    reason = models.CharField(max_length=10, choices=Reason.choices, blank=True, null=True)
    comment = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        verbose_name = "助手反馈"
        ordering = ("-updated_time", "-id")
        indexes = [models.Index(fields=["vote", "-updated_time", "-id"], name="tf_assistant_feedback_idx")]


class TicketAttachment(DbUuidModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    file = models.ForeignKey("file.UploadFile", on_delete=models.PROTECT, related_name="ticket_attachments")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "工单图片附件"
        ordering = ("sort_order", "created_time", "id")
        constraints = [models.UniqueConstraint(fields=["ticket", "file"], name="tf_ticket_attachment_once")]


class TicketChatMessage(DbUuidModel):
    class Kind(models.TextChoices):
        TEXT = "TEXT", "文本"
        IMAGE = "IMAGE", "图片"
        VIDEO = "VIDEO", "视频"
        SYSTEM = "SYSTEM", "系统"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="chat_messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.TEXT)
    content = models.TextField(blank=True, default="")
    attachment = models.ForeignKey(
        "file.UploadFile", on_delete=models.PROTECT, null=True, blank=True, related_name="ticket_chat_messages"
    )
    media_meta = models.JSONField(default=dict, blank=True)
    media_expired = models.BooleanField(default=False)
    client_msg_id = models.CharField(max_length=64, blank=True, default="")
    created_time = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "工单排查消息"
        ordering = ("created_time", "id")
        indexes = [models.Index(fields=["ticket", "created_time", "id"], name="tf_chat_msg_ticket_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "sender", "client_msg_id"],
                condition=~models.Q(client_msg_id=""),
                name="tf_chat_msg_client_once",
            )
        ]


class TicketChatReadState(DbUuidModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="chat_read_states")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    last_read_time = models.DateTimeField()

    class Meta:
        verbose_name = "工单会话已读游标"
        constraints = [models.UniqueConstraint(fields=["ticket", "user"], name="tf_chat_read_once")]
        indexes = [models.Index(fields=["user", "ticket"], name="tf_chat_read_user_idx")]
