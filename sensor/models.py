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


class PWSStation(models.Model):
    """PWS 스테이션 메타데이터"""
    stationID = models.CharField(max_length=100, unique=True)
    stationName = models.CharField(max_length=200, blank=True, default='')
    neighborhood = models.CharField(max_length=200, blank=True, default='')
    country = models.CharField(max_length=10, blank=True, default='')
    latitude = models.FloatField()
    longitude = models.FloatField()
    elevation = models.FloatField(null=True, blank=True)
    softwareType = models.CharField(max_length=100, blank=True, default='')
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pws_station'
        verbose_name = 'PWS Station'
        verbose_name_plural = 'PWS Stations'

    def __str__(self):
        return f"{self.stationID} - {self.stationName}"


class PWSObservation(models.Model):
    """PWS 원시 관측 데이터 (시계열 대용량)"""
    stationID = models.CharField(max_length=100, db_index=True)
    obsTimeUtc = models.DateTimeField(db_index=True)
    obsTimeLocal = models.CharField(max_length=100)

    # 온도/습도
    temperature = models.FloatField(null=True, blank=True)
    dewpoint = models.FloatField(null=True, blank=True)
    heatIndex = models.FloatField(null=True, blank=True)
    windChill = models.FloatField(null=True, blank=True)
    humidity = models.IntegerField(null=True, blank=True)

    # 기압
    pressure = models.FloatField(null=True, blank=True)

    # 풍속/풍향
    windSpeed = models.FloatField(null=True, blank=True)
    windGust = models.FloatField(null=True, blank=True)
    winddir = models.IntegerField(null=True, blank=True)

    # 강수량
    precipRate = models.FloatField(null=True, blank=True)
    precipTotal = models.FloatField(null=True, blank=True)

    # 태양/자외선
    solarRadiation = models.FloatField(null=True, blank=True)
    uv = models.FloatField(null=True, blank=True)

    # 품질 체크
    qcStatus = models.IntegerField(default=-1)

    class Meta:
        db_table = 'pws_observation'
        verbose_name = 'PWS Observation'
        verbose_name_plural = 'PWS Observations'
        unique_together = ('stationID', 'obsTimeUtc')
        indexes = [
            models.Index(fields=['stationID', 'obsTimeUtc']),
            models.Index(fields=['stationID']),
            models.Index(fields=['obsTimeUtc']),
        ]

    def __str__(self):
        return f"{self.stationID} - {self.obsTimeUtc}"


class PWSLatest(models.Model):
    """PWS 최신 데이터 스냅샷 (빠른 조회)"""
    stationID = models.CharField(max_length=100, unique=True)
    obsTimeUtc = models.DateTimeField()
    temperature = models.FloatField(null=True, blank=True)
    humidity = models.IntegerField(null=True, blank=True)
    pressure = models.FloatField(null=True, blank=True)
    windSpeed = models.FloatField(null=True, blank=True)
    windGust = models.FloatField(null=True, blank=True)
    winddir = models.IntegerField(null=True, blank=True)
    precipRate = models.FloatField(null=True, blank=True)
    dewpoint = models.FloatField(null=True, blank=True)
    heatIndex = models.FloatField(null=True, blank=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pws_latest'
        verbose_name = 'PWS Latest'
        verbose_name_plural = 'PWS Latest'

    def __str__(self):
        return f"{self.stationID} - {self.obsTimeUtc}"


class CCTVStation(models.Model):
    """CCTV 스테이션 메타데이터"""
    cctvID = models.CharField(max_length=100, unique=True)
    pws_station = models.CharField(max_length=100)
    url = models.URLField()
    location_name = models.CharField(max_length=200, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cctv_station'
        verbose_name = 'CCTV Station'
        verbose_name_plural = 'CCTV Stations'

    def __str__(self):
        return f"{self.cctvID} ({self.pws_station})"


class CCTVRecording(models.Model):
    """CCTV 녹화 기록"""
    STATUS_CHOICES = [
        ('recording', 'Recording'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    cctv_station = models.ForeignKey(CCTVStation, on_delete=models.CASCADE)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    file_path = models.CharField(max_length=500, blank=True)
    precipRate_trigger = models.FloatField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='recording')
    duration_minutes = models.IntegerField(null=True, blank=True)
    file_size_mb = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'cctv_recording'
        verbose_name = 'CCTV Recording'
        verbose_name_plural = 'CCTV Recordings'
        indexes = [
            models.Index(fields=['cctv_station', 'start_time']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.cctv_station.cctvID} - {self.start_time}"
