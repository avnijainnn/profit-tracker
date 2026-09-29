from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tracker", "0002_safeguards")]
    operations = [migrations.CreateModel(name="RecoveryThrottle", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("key", models.CharField(max_length=64, unique=True)),
        ("window_started", models.DateTimeField()),
        ("count", models.PositiveIntegerField(default=0)),
    ])]
