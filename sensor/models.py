from django.db import models


class SensorData(models.Model):
    """원시 센서 데이터 로그 (3,900만 건 이상의 대규모 테이블)"""
    sensor = models.CharField(max_length=100)
    mac = models.CharField(max_length=100)
    receiver = models.CharField(max_length=100)
    mode = models.CharField(max_length=20, choices=[('direct', 'Direct'), ('mobile', 'Mobile')])
    temperature = models.FloatField()
    co2 = models.IntegerField()
    sensing_time = models.FloatField()
    rssi = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'sensor_sensor_data'
        verbose_name = 'Sensor Data'
        verbose_name_plural = 'Sensor Data'
        indexes = [
            models.Index(fields=['sensor', 'sensing_time']),
        ]

    def __str__(self):
        return f"{self.sensor} - {self.temperature}°C, {self.co2}ppm"


class IpDb(models.Model):
    """센서 네트워크 IP 기록"""
    sensor = models.CharField(max_length=100)
    ip = models.CharField(max_length=100)
    time = models.IntegerField()

    class Meta:
        db_table = 'sensor_ip_db'
        verbose_name = 'Sensor IP'
        verbose_name_plural = 'Sensor IPs'

    def __str__(self):
        return f"{self.sensor} - {self.ip}"


class SensorCheckDb(models.Model):
    """직접 통신(direct) 센서의 최신 상태 스냅샷"""
    sensor = models.CharField(max_length=100)
    temperature = models.IntegerField()
    co2 = models.IntegerField()
    sensing_time = models.FloatField()

    class Meta:
        db_table = 'sensor_sensor_check_db'
        verbose_name = 'Sensor Check (Direct)'
        verbose_name_plural = 'Sensor Check (Direct)'

    def __str__(self):
        return f"{self.sensor} - {self.temperature}°C, {self.co2}ppm"


class MobileCheckDb(models.Model):
    """모바일 릴레이(mobile) 센서의 최신 상태 스냅샷"""
    sensor = models.CharField(max_length=100)
    temperature = models.IntegerField()
    co2 = models.IntegerField()
    rssi = models.IntegerField()
    receiver = models.CharField(max_length=100)
    sensing_time = models.FloatField()

    class Meta:
        db_table = 'sensor_mobile_check_db'
        verbose_name = 'Sensor Check (Mobile)'
        verbose_name_plural = 'Sensor Check (Mobile)'

    def __str__(self):
        return f"{self.sensor} - {self.temperature}°C, {self.co2}ppm"


class SensorLocation(models.Model):
    """센서 설치 위치 (위경도 좌표)"""
    sensor = models.CharField(max_length=100, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        db_table = 'sensor_location'
        verbose_name = 'Sensor Location'
        verbose_name_plural = 'Sensor Locations'

    def __str__(self):
        return f"{self.sensor} ({self.latitude}, {self.longitude})"
