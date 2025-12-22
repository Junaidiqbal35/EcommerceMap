from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0008_delete_spatialreferencesystem_and_more'),  # Update this to your latest migration
    ]

    operations = [
        migrations.CreateModel(
            name='UserLayerPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('download_count', models.IntegerField(default=1)),
                ('last_used', models.DateTimeField(auto_now=True)),
                ('is_favorite', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('layer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_preferences', to='core.layer')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='layer_preferences', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'User Layer Preference',
                'verbose_name_plural': 'User Layer Preferences',
                'ordering': ['-download_count', '-last_used'],
                'unique_together': {('user', 'layer')},
            },
        ),
    ]