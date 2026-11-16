# Additive only: every existing shop gets gst_enabled=False and keeps working exactly as before.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shops', '0006_shop_delivery_radius_km_shop_latitude_shop_longitude_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='shop',
            name='gst_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='shop',
            name='gst_enabled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='shop',
            name='gst_legal_name',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='shop',
            name='gst_trade_name',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AddField(
            model_name='shop',
            name='gst_address',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='shop',
            name='gst_scheme',
            field=models.CharField(choices=[('regular', 'Regular (tax invoice)'), ('composition', 'Composition (bill of supply)')], default='regular', max_length=12),
        ),
        migrations.AddField(
            model_name='shop',
            name='gst_state_code',
            field=models.CharField(default='07', max_length=2),
        ),
        migrations.CreateModel(
            name='ShopGstChange',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gst_enabled', models.BooleanField()),
                ('gst_scheme', models.CharField(max_length=12)),
                ('gstin_changed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('changed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('shop', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gst_changes', to='shops.shop')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
    ]
