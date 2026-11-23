import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0004_deptinfo_is_ticketflow_skill_group"),
        ("tickets", "0005_ticketrating"),
    ]

    operations = [
        migrations.CreateModel(
            name="CategoryRoute",
            fields=[
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("ACCOUNT", "账户"),
                            ("ACCESS", "权限"),
                            ("NETWORK", "网络"),
                            ("SERVICE", "服务"),
                            ("OTHER", "其他"),
                        ],
                        max_length=12,
                        primary_key=True,
                        serialize=False,
                        verbose_name="分类",
                    ),
                ),
                (
                    "skill_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_routes",
                        to="identity.deptinfo",
                    ),
                ),
            ],
        ),
    ]
