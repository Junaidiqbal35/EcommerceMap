# Generated by Django 5.1.2 on 2024-10-08 21:50

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Server',
            fields=[
                ('id', models.IntegerField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('url', models.URLField()),
                ('extent_min_x', models.FloatField()),
                ('extent_min_y', models.FloatField()),
                ('extent_max_x', models.FloatField()),
                ('extent_max_y', models.FloatField()),
            ],
        ),
        migrations.CreateModel(
            name='Layer',
            fields=[
                ('layer_id', models.IntegerField(primary_key=True, serialize=False)),
                ('type', models.CharField(choices=[('point', 'Point'), ('line', 'Line'), ('polygon', 'Polygon')], max_length=10)),
                ('number', models.IntegerField()),
                ('name', models.CharField(max_length=255)),
                ('offsetX', models.FloatField(default=0)),
                ('offsetY', models.FloatField(default=0)),
                ('symbol', models.CharField(blank=True, max_length=255, null=True)),
                ('insert', models.CharField(blank=True, max_length=255, null=True)),
                ('server', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='layers', to='core.server')),
            ],
        ),
    ]
