import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sensor', '0006_sensordata_sensor_sens_sensing_60aa2e_idx'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cctvrecording',
            name='start_time',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
