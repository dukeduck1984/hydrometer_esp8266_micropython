# This file contains hardware configurations. e.g. Pin assignments
from micropython import const


PIN_I2C_SDA = const(21)
PIN_I2C_SCL = const(22)

PIN_BAT_ADC = const(35)  # for measuring battery voltage
PIN_VPP = const(23)  # for controlling peripheral power supply
PIN_MODE = const(27)  # for switching working mode

PIN_ONEWIRE = const(16)  # data line of DS18B20 temp sensor

PIN_LED_MODE = const(5)  # Led indicating the operation mode
PIN_LED_MODE_LOW_ACTIVE = const(1)  # whether or not the led is low active
PIN_LED_GRN = const(25)  # Led indicating healthy battery level
PIN_LED_GRN_LOW_ACTIVE = const(0)  # whether or not the led is low active
PIN_LED_RED = const(26)  # Led indicating low battery level
PIN_LED_RED_LOW_ACTIVE = const(0)  # whether or not the led is low active

FLAG_DEEPSLEEP = 'deepsleep.flag'
FLAG_FIRSTSLEEP = 'firstsleep.flag'
FLAG_FTP = 'ftp.flag'

FIRSTSLEEP_DURATION_MS = const(1200000)  # 20 minutes
# FIRSTSLEEP_DURATION_MS = const(60000)  # 1 minute, fot testing purpose

PATH_SETTING_FILE = 'user_settings.json'  # saves user settings
PATH_REGRESSION_FILE = 'regression.json'  # saves regression params

BAT_VOLTAGE_THRESHOLD = 3.66  # threshold for battery health check
