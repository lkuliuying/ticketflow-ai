from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0003_rename_default_root_department"),
    ]

    operations = [
        migrations.AddField(
            model_name="deptinfo",
            name="is_ticketflow_skill_group",
            field=models.BooleanField(db_default=False, default=False, verbose_name="工单技能组"),
        ),
    ]
