import esp
import machine
import ujson
import utime
import utilities as util

from config import *


# disable os debug info
esp.osdebug(None)

# Loading user settings from JSON file
settings = util.load_settings()

# Initialize VPP pin
vpp = util.init_vpp()


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


if machine.reset_cause() == machine.SOFT_RESET:
    # 初次进入休眠状态
    if util.in_firstsleep_mode():
        util.remove_flag_firstsleep()
        util.create_flag_deepsleep()
        util.pull_hold_pins()
        machine.deepsleep(FIRSTSLEEP_DURATION_MS)
    # 工作模式下的休眠状态
    elif util.in_deepsleep_mode():
        util.pull_hold_pins()
        machine.deepsleep(settings['deepSleepIntervalMs'])
    # FTP开启
    elif util.in_ftp_mode():
        util.remove_flag_ftp()
        wifi = util.init_wifi()
        led_mode = util.init_led_mode()
        led_mode.on()
        open_wireless(wifi)
        print('Initializing FTP service')
        utime.sleep_ms(500)
    # 进入校准模式
    else:
        import gc
        # Turn on VPP to supply power for GY521
        vpp.on()
        # Initialize the peripherals
        gy521 = util.init_gy521()
        ds18 = util.init_ds18b20()
        battery = util.init_lipo_adc()
        wifi = util.init_wifi()
        print('Entering Calibration Mode...')
        print('--------------------')
        # 1. Turn on the on-board led to indicate calibration mode
        led_mode = util.init_led_mode()
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

# Working mode
elif machine.reset_cause() == machine.DEEPSLEEP_RESET:
    from microWebCli import MicroWebCli
    # Unhold the pins to allow those pins to be used
    util.unhold_pins()
    # Turn on VPP to supply power for GY521 and allow battery voltage measurement
    vpp.on()
    # Initialize the peripherals
    gy521 = util.init_gy521()
    ds18 = util.init_ds18b20()
    battery = util.init_lipo_adc()
    wifi = util.init_wifi()
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
        util.remove_flag_deepsleep()
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
    param_a, param_b, param_c, unit = util.load_regression_params()
    if not (param_a and param_b and param_c):
        print('The Hydrometer should be calibrated before use.')
        print('Entering Calibration Mode in 5sec...')
        util.remove_flag_deepsleep()
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
        machine_id = util.get_machine_id()
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
    util.create_flag_deepsleep()
    print('Sleeping now...')
    machine.reset()

# Power-on, calibration mode can be activated within 1 minute, otherwise it will deepsleep to enter working mode
else:
    util.remove_flag_deepsleep()
    util.remove_flag_firstsleep()

    # Initialize LEDs and battery power management
    led_mode = util.init_led_mode()
    led_red = util.init_led_red()
    led_grn = util.init_led_grn()
    vpp.on()
    bat = util.init_lipo_adc()
    voltage = bat.get_lipo_voltage()
    vpp.off()
    # Green light indicates healthy battery level
    # Red light means the battery is low
    if voltage >= BAT_VOLTAGE_THRESHOLD:
        led_grn.on()
        led_red.off()
    else:
        led_grn.off()
        led_red.on()

    # Initialize the mode switch (a double-pole single-throw switch)
    mode_switch = util.init_mode_switch()
    print('--------------------')
    print('First time power on...')
    print('If you wish to enter Calibration Mode, pls trigger the mode switch within 1 minute.')
    print('The system will go into Working Mode when 1 minute is out.')

    def first_sleep():
        util.create_flag_firstsleep()
        utime.sleep_ms(500)
        machine.reset()

    reboot_tim = machine.Timer(-1)
    # 1分钟后触发Deep-Sleep，再次唤醒后便进入工作模式开始采集数据
    reboot_tim.init(period=60000, mode=machine.Timer.ONE_SHOT, callback=lambda t: first_sleep())
    irq_counter = 0
    # 通过干簧管开关触发重启，进入校准模式

    def switch_cb():
        global irq_counter
        if irq_counter < 1:
            irq_counter += 1
            led_red.off()
            led_grn.off()
            print('Rebooting to enter Calibration Mode...')
            utime.sleep_ms(3000)
            machine.reset()

    mode_switch.irq(handler=lambda pin: switch_cb(), trigger=machine.Pin.IRQ_FALLING)

    # Flashing the LED to indicate the system is standing by user's action
    while True:
        led_mode.on()
        utime.sleep_ms(500)
        led_mode.off()
        utime.sleep_ms(500)
