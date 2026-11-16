# Additive only: existing listings get no GST rate (unconfirmed), no HSN, and prices that include GST.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_shopproduct_online_visible'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopproduct',
            name='gst_rate',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='shopproduct',
            name='hsn_code',
            field=models.CharField(blank=True, max_length=8),
        ),
        migrations.AddField(
            model_name='shopproduct',
            name='price_includes_gst',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='shopproduct',
            name='gst_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
