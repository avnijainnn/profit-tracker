from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def check_references(apps, schema_editor):
    Entry = apps.get_model("tracker", "Entry")
    duplicates = (Entry.objects.using(schema_editor.connection.alias).filter(voided_at__isnull=True)
                  .exclude(reference="").values("owner_id", "account_id", "reference")
                  .annotate(count=models.Count("pk")).filter(count__gt=1))
    if duplicates.exists():
        raise RuntimeError("Active duplicate statement references exist. Back up the database and review/void duplicate entries before retrying migration 0002. Nothing was deleted.")


class Migration(migrations.Migration):
    dependencies = [("tracker", "0001_initial")]
    operations = [
        migrations.RunPython(check_references, migrations.RunPython.noop),
        migrations.AddField(model_name="entry", name="revision", field=models.PositiveIntegerField(default=1)),
        migrations.AddConstraint(model_name="entry", constraint=models.UniqueConstraint(
            fields=("owner", "account", "reference"), condition=models.Q(voided_at__isnull=True) & ~models.Q(reference=""),
            name="unique_active_statement_reference")),
        migrations.CreateModel(name="Submission", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("token", models.UUIDField()), ("fingerprint", models.CharField(max_length=64)),
            ("object_id", models.PositiveBigIntegerField()), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={"constraints": [models.UniqueConstraint(fields=("owner", "token"), name="unique_owner_submission")]}),
        migrations.CreateModel(name="MonthReview", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("month", models.DateField()), ("closed_at", models.DateTimeField(null=True, blank=True)),
            ("snapshot", models.JSONField(default=dict)), ("revision", models.PositiveIntegerField(default=0)),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-month"], "constraints": [models.UniqueConstraint(fields=("owner", "month"), name="unique_owner_review")]}),
        migrations.CreateModel(name="StockReversal", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("reason", models.TextField()), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("movement", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="reversal", to="tracker.stockmovement")),
            ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-created_at", "-pk"]}),
    ]
