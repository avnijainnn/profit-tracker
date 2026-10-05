from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tracker", "0011_product_photo")]

    operations = [
        migrations.AlterField(model_name="changelog", name="details", field=models.JSONField(blank=True, default=dict)),
        migrations.AlterField(model_name="monthreview", name="snapshot", field=models.JSONField(blank=True, default=dict)),
    ]
