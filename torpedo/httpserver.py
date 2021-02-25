import machine
import ujson

from config import FLAG_FIRSTSLEEP, FLAG_FTP
from microWebSrv import MicroWebSrv


class HttpServer:
    def __init__(self, gy521_obj, wifi_obj, user_settings_dict):
        self.gy521 = gy521_obj
        self.wifi = wifi_obj
        self.settings = user_settings_dict
        self.app = None

    def start(self):
        gy521 = self.gy521
        wifi = self.wifi
        settings = self.settings

        @MicroWebSrv.route('/connecttest')
        def test_get(httpClient, httpResponse):
            """
            测试前端和后端之间的网络连接
            """
            httpResponse.WriteResponseOk()

        # Define the web routes and functions
        @MicroWebSrv.route('/tilt')
        def tilt_get(httpClient, httpResponse):
            """
            读取比重计倾角，前端每10秒请求1次
            """
            try:
                _, tilt, _ = gy521.read_angles()
            except:
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseJSONOk(obj={'tilt': tilt}, headers=None)

        @MicroWebSrv.route('/calibration', 'POST')
        def calibration_post(httpClient, httpResponse):
            """
            前台进行倾角与比重的拟合计算后，将比重单位和拟合系数发回后台保存
            """
            result = httpClient.ReadRequestContentAsJSON()
            try:
                with open('regression.json', 'w') as f:
                    ujson.dump(result, f)
            except:
                # throw 500 error code
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseOk()

        @MicroWebSrv.route('/calibration')
        def calibration_get(httpClient, httpResponse):
            """
            将上一次保存的校准参数从json文件中读取并发送到前台
            """
            try:
                with open('regression.json', 'r') as f:
                    params = ujson.load(f)
            except:
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseJSONOk(obj={'params': params}, headers=None)

        @MicroWebSrv.route('/settings')
        def settings_get(httpClient, httpResponse):
            """
            从后台读取设置参数
            """
            wifi_list = wifi.scan_wifi_list()
            settings_added = {
                'wifiList': wifi_list
            }
            settings_combined = settings.copy()
            settings_combined.update(settings_added)
            httpResponse.WriteResponseJSONOk(obj=settings_combined, headers=None)

        @MicroWebSrv.route('/settings', 'POST')
        def settings_post(httpClient, httpResponse):
            """
            向后台保存设置参数
            """
            settings_dict = httpClient.ReadRequestContentAsJSON()
            try:
                with open('user_settings.json', 'w') as f:
                    ujson.dump(settings_dict, f)
            except:
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseOk()

        @MicroWebSrv.route('/reboot')
        def reboot_get(httpClient, httpResponse):
            """
            重启ESP32
            """
            tim = machine.Timer(-1)
            try:
                tim.init(period=3000, mode=machine.Timer.ONE_SHOT, callback=lambda t: machine.reset())
            except:
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseOk()

        @MicroWebSrv.route('/deepsleep')
        def deepsleep_get(httpClient, httpResponse):
            """
            使ESP32进入深度睡眠，唤醒后便进入工作模式
            """
            def first_sleep():
                with open(FLAG_FIRSTSLEEP, 'w') as s:
                    pass
                machine.reset()

            tim = machine.Timer(-1)
            try:
                tim.init(period=3000, mode=machine.Timer.ONE_SHOT, callback=lambda t: first_sleep())
            except:
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseOk()

        @MicroWebSrv.route('/wifi')
        def wifi_get(httpClient, httpResponse):
            """
            获取WIFI热点列表，用于刷新热点列表
            """
            wifi_list = wifi.scan_wifi_list()
            wifi_dict = {'wifiList': wifi_list}
            httpResponse.WriteResponseJSONOk(obj=wifi_dict, headers=None)

        @MicroWebSrv.route('/wifi', 'POST')
        def wifi_post(httpClient, httpResponse):
            """
            连接WIFI热点
            """
            wifi_dict = httpClient.ReadRequestContentAsJSON()
            new_ip = wifi.sta_connect(wifi_dict['ssid'], wifi_dict['pass'])
            if new_ip:
                # 200
                httpResponse.WriteResponseOk()
            else:
                # throw 500 error code
                httpResponse.WriteResponseInternalServerError()

        @MicroWebSrv.route('/ftp')
        def ftp_get(httpClient, httpResponse):
            """
            Start FTP service
            """
            def start_ftp():
                with open(FLAG_FTP, 'w') as s:
                    pass
                machine.reset()

            tim = machine.Timer(-1)
            try:
                tim.init(period=3000, mode=machine.Timer.ONE_SHOT, callback=lambda t: start_ftp())
            except:
                httpResponse.WriteResponseInternalServerError()
            else:
                httpResponse.WriteResponseOk()

        @MicroWebSrv.route('/mqtttest', 'POST')
        def mqtt_post(httpClient, httpResponse):
            """
            Send test message to MQTT server
            """
            settings_dict = httpClient.ReadRequestContentAsJSON()
            test_msg = {'test-message': 200}
            str_data = ujson.dumps(test_msg)
            from mqtt_client import MQTT
            try:
                client = MQTT(settings_dict)
                client.publish(str_data)
            except:
                print('Failed to send the message to the MQTT broker.')
                httpResponse.WriteResponseInternalServerError()
            else:
                print('The test message has been sent successfully.')
                httpResponse.WriteResponseOk()

        # Initialize the Web server
        self.app = MicroWebSrv(webPath='/www')
        self.app.Start(threaded=True)  # Starts the server

    def stop(self):
        if self.app:
            self.app.Stop()

    def is_started(self):
        if self.app:
            return self.app.IsStarted()
        else:
            return False
