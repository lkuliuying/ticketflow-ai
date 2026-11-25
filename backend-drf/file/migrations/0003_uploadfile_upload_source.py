from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("file", "0002_initial")]

    operations = [
        migrations.AddField(
            model_name="uploadfile",
            name="upload_source",
            field=models.CharField(blank=True, default="", editable=False, max_length=32),
        ),
    ]
