import esp
import machine
import ujson
import utime

from config import *

# disable os debug info
esp.osdebug(None)
print('--------------------')
# Loading user settings from JSON file
with open('user_settings.json', 'r') as f:
    json = f.read()
settings = ujson.loads(json)
print('File "user_settings.json" has been loaded!')
print('--------------------')

# Initialize VPP pin
vpp = machine.Pin(PIN_VPP, machine.Pin.OUT, value=0)
print('The VPP pin has been initialized')
print('--------------------')


def initialization(init_gy521=True, init_ds18=True, init_bat=True, init_wifi=True):
    """
    Initialize GY521 module, battery ADC pin and wifi
    NOTE: VPP pin must be turned on in order to initialize the GY521 module
    """
    if init_gy521:
        from gy521 import GY521
        # Initialize the GY521 module
        print('Initializing GY521 module')
        try:
            gy521_sensor = GY521(PIN_I2C_SDA, PIN_I2C_SCL)
        except Exception as e:
            print(e)
            gy521_sensor = None
    else:
        gy521_sensor = None

    if init_ds18:
        from tempsensor import Ds18Sensors, SingleTempSensor
        print('Initializing DS18B20 sensor')
        try:
            ow = Ds18Sensors(PIN_ONEWIRE)
            romcode_string = ow.get_device_list()[0].get('value')
            ds18_sensor = SingleTempSensor(ow, romcode_string)
        except Exception as e:
            print(e)
            ds18_sensor = None
    else:
        ds18_sensor = None

    if init_bat:
        from battery import Battery
        # Initialize the battery power management
        print('Initializing power management')
        lipo = Battery(PIN_BAT_ADC)
    else:
        lipo = None

    if init_wifi:
        from wifi import WiFi
        # Initialize Wifi
        print('Initializing WiFi')
        wlan = WiFi()
    else:
        wlan = None
    return gy521_sensor, ds18_sensor, lipo, wlan


def open_wireless(wlan):
    wlan.ap_start(settings['apSsid'])
    print('AP started')
    # get the AP IP of ESP32 itself, usually it's 192.168.4.1
    ap_ip = wlan.get_ap_ip_addr()
    print('AP IP: ' + ap_ip)
    # get the Station IP of ESP32 in the WLAN which ESP32 connects to
    if settings['wifi']['ssid']:
        sta_ip = wlan.sta_connect(settings['wifi']['ssid'], settings['wifi']['pass'], verify_ap=True)
        if sta_ip:
            print('STA IP: ' + sta_ip)
    print('--------------------')


def pull_hold_pins():
    """
    Set output pins to input with pull hold to save power consumption
    """
    machine.Pin(PIN_I2C_SDA, machine.Pin.IN, machine.Pin.PULL_HOLD)
    machine.Pin(PIN_I2C_SCL, machine.Pin.IN, machine.Pin.PULL_HOLD)
    machine.Pin(PIN_VPP, machine.Pin.IN, machine.Pin.PULL_HOLD)
    machine.Pin(PIN_LED_MODE, machine.Pin.IN, machine.Pin.PULL_HOLD)
    machine.Pin(PIN_LED_RED, machine.Pin.IN, machine.Pin.PULL_HOLD)
    machine.Pin(PIN_LED_GRN, machine.Pin.IN, machine.Pin.PULL_HOLD)


def unhold_pins():
    """
    Unhold the pins after wake up from deep sleep
    """
    machine.Pin(PIN_I2C_SDA, machine.Pin.OUT, None)
    machine.Pin(PIN_I2C_SCL, machine.Pin.OUT, None)
    machine.Pin(PIN_VPP, machine.Pin.OUT, None)
    # machine.Pin(PIN_LED_MODE, machine.Pin.OUT, None, value=1)
    # machine.Pin(PIN_LED_RED, machine.Pin.OUT, None)
    # machine.Pin(PIN_LED_GRN, machine.Pin.OUT, None)


def init_leds():
    """
    Initialize the on-board LED which is on pin5 and active low
    """
    # The on-board led of the Wemos Lolin32 is low active
    led_mode = machine.Signal(
        machine.Pin(PIN_LED_MODE, machine.Pin.OUT, value=PIN_LED_MODE_LOW_ACTIVE),
        invert=True if PIN_LED_MODE_LOW_ACTIVE else False
    )
    led_red = machine.Signal(
        machine.Pin(PIN_LED_RED, machine.Pin.OUT, value=PIN_LED_RED_LOW_ACTIVE),
        invert=True if PIN_LED_RED_LOW_ACTIVE else False
    )
    led_grn = machine.Signal(
        machine.Pin(PIN_LED_GRN, machine.Pin.OUT, value=PIN_LED_GRN_LOW_ACTIVE),
        invert=True if PIN_LED_GRN_LOW_ACTIVE else False
    )
    return led_mode, led_red, led_grn


if machine.reset_cause() == machine.SOFT_RESET:
    import uos

    # 初次进入休眠状态
    if FLAG_FIRSTSLEEP in uos.listdir():
        uos.remove(FLAG_FIRSTSLEEP)
        with open(FLAG_DEEPSLEEP, 'w') as f:
            pass
        pull_hold_pins()
        machine.deepsleep(FIRSTSLEEP_DURATION_MS)
    # 工作模式下的休眠状态
    elif FLAG_DEEPSLEEP in uos.listdir():
        pull_hold_pins()
        machine.deepsleep(settings['deepSleepIntervalMs'])
    # FTP开启
    elif FLAG_FTP in uos.listdir():
        uos.remove(FLAG_FTP)
        _, _, _, wifi = initialization(init_gy521=False, init_ds18=False, init_bat=False, init_wifi=True)
        led_mode, _, _ = init_leds()
        led_mode.on()
        open_wireless(wifi)
        print('Initializing FTP service')
        utime.sleep_ms(500)
        import uftpd
    # 进入校准模式
    else:
        import gc
        # Turn on VPP to supply power for GY521
        vpp.on()
        # Initialize the peripherals
        gy521, ds18, battery, wifi = initialization(init_gy521=True, init_ds18=True, init_bat=True, init_wifi=True)
        print('Entering Calibration Mode...')
        print('--------------------')
        # 1. Turn on the on-board green led to indicate calibration mode
        led_mode, _, _ = init_leds()
        led_mode.on()
        # 2. Start WLAN in AP & STA mode to allow wifi connection
        utime.sleep_ms(1000)
        open_wireless(wifi)
        # 3. Measure tilt angle every 3s in the background
        import _thread

        def measure_tilt():
            while True:
                try:
                    gy521.get_smoothed_angles()
                except Exception:
                    print('Error occurs when measuring tilt angles')
                gc.collect()
                utime.sleep_ms(3000)

        tilt_th = _thread.start_new_thread(measure_tilt, ())
        # 4. Set up HTTP Server
        from httpserver import HttpServer
        web = HttpServer(gy521, wifi, settings)
        print('HTTP server initialized')
        web.start()
        utime.sleep_ms(3000)
        if web.is_started():
            print('HTTP service started')
        print('--------------------')
# 工作模式
elif machine.reset_cause() == machine.DEEPSLEEP_RESET:
    import uos
    from microWebCli import MicroWebCli
    # Unhold the pins to allow those pins to be used
    unhold_pins()
    # Turn on VPP to supply power for GY521 and allow battery voltage measurement
    vpp.on()
    # Initialize the peripherals
    gy521, ds18, battery, wifi = initialization(init_gy521=True, init_ds18=True, init_bat=True, init_wifi=True)
    print('Entering Working Mode...')
    utime.sleep_ms(500)
    send_data_to_fermenter = settings['fermenterAp']['enabled']
    send_data_to_mqtt = settings['mqtt']['enabled']
    # 1. Start WLAN in STA mode and connect to AP
    if send_data_to_mqtt:
        ssid = settings['wifi'].get('ssid')
        pswd = settings['wifi'].get('pass')
    else:
        ssid = settings['fermenterAp'].get('ssid')
        pswd = settings['fermenterAp'].get('pass')

    if ssid:
        sta_ip_addr = wifi.sta_connect(ssid, pswd)
        if sta_ip_addr:
            print('STA IP: ' + sta_ip_addr)
    else:
        print('Pls set up the Wifi connection first.')
        print('Entering Calibration Mode in 5sec...')
        if FLAG_DEEPSLEEP in uos.listdir():
            uos.remove(FLAG_DEEPSLEEP)
        utime.sleep_ms(5000)
        machine.reset()
    print('--------------------')
    # 2. Measure Lipo battery level
    battery_voltage = battery.get_lipo_voltage()
    utime.sleep_ms(200)
    battery_percent = battery.get_lipo_level()
    # 3. Measure tilt angle
    _, tilt, _ = gy521.get_smoothed_angles()
    utime.sleep_ms(200)
    # 4. Measure temperature
    try:
        ds18.read_temp()
        utime.sleep_ms(100)
        temp = ds18.read_temp()
    except Exception as e:
        print(e)
        temp = None
    # 5. Turn off VPP to save power
    vpp.off()
    # 6. Calculate Specific Gravity
    with open('regression.json', 'r') as f:
        json = f.read()
    reg = ujson.loads(json)
    param_a = reg.get('a')
    param_b = reg.get('b')
    param_c = reg.get('c')
    unit = reg.get('unit')
    if not (param_a and param_b and param_c):
        print('The Hydrometer should be calibrated before use.')
        print('Entering Calibration Mode in 5sec...')
        utime.sleep_ms(5000)
        machine.reset()
    gravity = param_a * tilt**2 + param_b * tilt + param_c
    if unit == 'p':
        sg = round(1 + (gravity / (258.6 - ((gravity / 258.2) * 227.1))), 3)
        plato = round(gravity, 1)
    else:
        sg = round(gravity, 3)
        plato = round((-1 * 616.868) + (1111.14 * gravity) - (630.272 * gravity ** 2) + (135.997 * gravity ** 3), 1)

    if wifi.is_connected():
        machine_id = int.from_bytes(machine.unique_id(), 'big')
        # 5.1. Send Specific Gravity data & battery level by MQTT
        if send_data_to_mqtt:
            from mqtt_client import MQTT
            # Format for ChinaMobile OneNET IoT platform
            if settings.get('mqtt').get('brokerAddr') == '183.230.40.96' and\
                    settings.get('mqtt').get('brokerPort') == 1883:
                hydrometer_dict = {
                    # 'id': machine_id,
                    'id': 123,
                    'dp': {
                        'temperature': [{'v': temp}],
                        'sg': [{'v': sg}],
                        'plato': [{'v': plato}],
                        'battery': [{'v': battery_voltage}]
                    }
                }
            else:
                hydrometer_dict = {
                    'temperature': temp,
                    'sg': sg,
                    'plato': plato,
                    'battery': battery_voltage
                }
            mqtt_data = ujson.dumps(hydrometer_dict)
            client = MQTT(settings)
            client.publish(mqtt_data)
        # 5.2. Send Specific Gravity data & battery level to Fermenter ESP32 by HTTP
        else:
            hydrometer_dict = {
                'name': settings.get('apSsid'),
                'ID': machine_id,
                'temperature': temp,
                'angle': tilt,
                'battery': battery_voltage,
                'fahrenheit': round(temp * 1.8 + 32, 1),
                'currentGravity': sg,
                'currentPlato': plato,
                'batteryLevel': battery_percent,
                'updateIntervalMs': int(settings['deepSleepIntervalMs'])
            }

            host = settings['fermenterAp']['host']
            api = settings['fermenterAp']['api']
            if not host.startswith('http://'):
                host = 'http://' + host.strip()
            if host.endswith('/'):
                host = host[:-1]
            if not api.startswith('/'):
                api = '/' + api.strip()
            url = host + api
            # api_url='/api/hydrometer/v1/data',  # CraftBeerPi3 API

            cli = MicroWebCli(
                # Fermenter ESP32 API
                url=url,
                # Postman mock server for testing
                # url='https://ba36095e-b0f1-430a-80a8-e32eb8663be8.mock.pstmn.io/gravity',
                method='POST',
                connTimeoutSec=60
            )
            req_counter = 0
            while req_counter < 3:
                print('Sending hydrometer data to the fermenter...')
                print('URL: ' + url)
                print(hydrometer_dict)
                try:
                    cli.OpenRequestJSONData(o=hydrometer_dict)
                except Exception:
                    print('Error: Cannot reach the server.')
                    print('Will retry in 3sec...')
                    utime.sleep_ms(3000)
                    req_counter += 1
                else:
                    resp = cli.GetResponse()
                    if not resp.IsSuccess():
                        print('Error ' + str(resp.GetStatusCode()) + ': ' + resp.GetStatusMessage())
                        print('Will retry in 3sec...')
                        utime.sleep_ms(3000)
                        req_counter += 1
                        print('Retry #' + str(req_counter))
                    else:
                        print('Data sent successfully!')
                        break
        wifi.sta_disconnect()
        utime.sleep_ms(200)
    # 6. Go deep sleep again, and will wake up after sometime to repeat above.
    with open(FLAG_DEEPSLEEP, 'w') as f:
        pass
    print('Sleeping now...')
    machine.reset()
# 首次开机，用户有1分钟时间出发模式选择开关进去校准模式; 1分钟之后程序会进入DEEP-SLEEP模式，再次唤醒后将开始工作
else:
    import uos

    if FLAG_DEEPSLEEP in uos.listdir():
        uos.remove(FLAG_DEEPSLEEP)
    if FLAG_FIRSTSLEEP in uos.listdir():
        uos.remove(FLAG_FIRSTSLEEP)

    # Initialize LEDs and battery power management
    led_mode, led_red, led_grn = init_leds()
    vpp.on()
    _, _, bat, _ = initialization(init_gy521=False, init_ds18=False, init_bat=True, init_wifi=False)
    voltage = bat.get_lipo_voltage()
    vpp.off()
    # Green light indicates healthy battery level
    # Red light means the battery is low
    if voltage >= 3.66:
        led_grn.on()
        led_red.off()
    else:
        led_grn.off()
        led_red.on()

    # Initialize the mode switch (a double-pole single-throw switch)
    print("Initializing the mode switch")
    mode_switch = machine.Pin(PIN_MODE, machine.Pin.IN, machine.Pin.PULL_UP)
    print('--------------------')
    print('First time power on...')
    print('If you wish to enter Calibration Mode, pls trigger the mode switch within 1 minute.')
    print('The system will go into Working Mode when 1 minute is out.')

    def first_sleep():
        with open(FLAG_FIRSTSLEEP, 'w') as s:
            pass
        utime.sleep_ms(500)
        machine.reset()

    reboot_tim = machine.Timer(-1)
    # 1分钟后触发Deep-Sleep，再次唤醒后便进入工作模式开始采集数据
    reboot_tim.init(period=60000, mode=machine.Timer.ONE_SHOT, callback=lambda t: first_sleep())
    irq_counter = 0
    # 通过干簧管开关触发重启，进入校准模式

    def switch_cb(pin):
        global irq_counter
        if irq_counter < 1:
            irq_counter += 1
            led_red.off()
            led_grn.off()
            machine.disable_irq()
            print('Rebooting to enter Calibration Mode...')
            utime.sleep_ms(3000)
            machine.reset()

    mode_switch.irq(handler=switch_cb, trigger=machine.Pin.IRQ_FALLING)

    # Flashing the LED to indicate the system is standing by user's action
    while True:
        led_mode.on()
        utime.sleep_ms(500)
        led_mode.off()
        utime.sleep_ms(500)
