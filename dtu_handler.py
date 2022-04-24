import sim, uos, dataCall, ujson, net, modem, utime, _thread, uhashlib, fota, ure, ubinascii, cellLocator, log, request
from machine import Pin
from machine import UART

from usr.singleton import Singleton
from usr.offline_storage import OfflineStorage
from usr.quecthing import QuecthingDtuTransfer
from usr.dtu_mqtt import DtuMqttTransfer
from usr.huawei_cloud import HuaweiCloudTransfer
from usr.aliyun import ALYDtuMqttTransfer
from usr.tencent_cloud import TXYDtuMqttTransfer
from usr.dtu_request import DtuRequest
from usr.tcp_udpsocket import TcpSocket
from usr.tcp_udpsocket import UdpSocket
from usr.uart import DtuUart
from usr.settings import DTUDocumentData
from usr.settings import ProdDocumentParse
from usr.settings import CONFIG
from usr.command import ChannelTransfer
from usr.dtu_log import RET
from usr.dtu_log import error_map

log.basicConfig(level=log.INFO)
logger = log.getLogger(__name__)

@Singleton
class ProdDtu(object):

    def __init__(self):
        self.gpio = None
        self.uart = None
        self.parse_data = None
        self.document_parser = None
        self.channel = None
        self.offline_storage = None
        self.cloud_protocol = None
        #self.apn = None
        #self.ota = None
        #self.pins = None
        self.channels = None
        self.off_storage = None

    def set_gpio(self, gpio):
        self.gpio = gpio

    def set_uart(self, uart):
        self.uart = uart

    def set_parse_data(self, parse_data):
        self.parse_data = parse_data

    def set_document_parser(self, document_parser):
        self.document_parser = document_parser

    def set_channels(self, channels):
        self.channels = channels
    
    def set_off_storage(self, offline_storage):
        self.offline_storage = offline_storage


    def prepare(self):
        while True:
            if not sim.getStatus():
                if not self.gpio.status():
                    self.gpio.show()
                utime.sleep(1)
            else:
                break

    def dialing(self):
        # 文件备份
        call_count = 0
        if self.parse_data.apn[0] != "" and self.parse_data.apn[1] != "" and self.parse_data.apn[2] != "":
            while True:
                res = dataCall.setApn(1, 0, self.parse_data.apn[0], self.parse_data.apn[1], self.parse_data.apn[2], 0)
                if res == 0:
                    print("APN datacall successful")
                    break
                if res == -1:
                    print("Try APN datacall...")
                    call_count += 1
                    utime.sleep(1)
                    if call_count > 10:
                        logger.error("Datacall failed, please restart device and run again.")
                        break
        # else:
        #     while True:
        #         res = dataCall.start(1, 0, "3gnet.mnc001.mcc460.gprs", "", "", 0)
        #         if res == 0:
        #             print("datacall successful")
        #             break
        #         if res == -1:
        #             print("Try datacall...")
        #             call_count += 1
        #             utime.sleep(1)
        #             if call_count > 10:
        #                 logger.error("Datacall failed, please restart device and run again.")
        #                 break
        count = 0
        max_count = 10
        while count < max_count:
            if not dataCall.getInfo(1, 0)[2][0]:
                utime.sleep(1)
                if not self.gpio.status():
                    self.gpio.show()
                utime.sleep(1)
            else:
                break

    def parse(self): # 更新DTUDocumentData（）
        self.document_parser.parse(self.parse_data)

    def request(self):
        print("ota: ", self.parse_data.ota)
        if self.parse_data.ota[0] == "" or self.parse_data.ota[1] == "" or self.parse_data.ota[2] == "":
            if self.ota[0] == "":
                logger.info("no uid params")
            if self.ota[1] == "":
                logger.info("no module_type params")
            if self.ota[2] == "":
                logger.info("no pk params")
            print("close ota update")
            return
        # 脚本升级
        do_fota = self.parse_data.fota
        if do_fota == 1:
            if "apn_cfg.json" in uos.listdir():  # 旧版本固件
                usr = ""
            else:  # 新固件
                usr = "usr/"
            global url_zip, targetVersion, fileMD5, action, filesize
            # 获取access token
            url = "https://cloudota.quectel.com:8100/v1/oauth/token"
            imei = modem.getDevImei()
            secret = ubinascii.hexlify(uhashlib.md5("QUEC" + str(imei) + "TEL").digest())
            secret = secret.decode()
            # print(url + "?imei=" + imei + "&" + "secret=" + secret)
            resp = request.get(url + "?imei=" + imei + "&" + "secret=" + secret)
            if resp.status_code != 200:
                logger.info("***********acquire token failed!***********")
                return
            data = ""
            for i in resp.content:
                data += i.decode()
            json_data = ujson.loads(data)
            access_token = json_data["data"]["access_Token"]
            print("access_token:", access_token)
            # 升级包下载地址的请求
            version = self.parse_data.version
            moduleType = self.parse_data.ota[1]
            download_url = "https://cloudota.quectel.com:8100/v1/fota/fw"
            headers = {"access_token": access_token, "Content-Type": "application/json"}
            acquire_data = {
                "version": str(version),
                "imei": imei,
                "moduleType": moduleType,
                "battery": 100,
                "rsrp": net.csqQueryPoll(),
                "uid": self.parse_data.ota[0],
                "pk": self.parse_data.ota[2]
            }
            resp = request.post(download_url, data=ujson.dumps(acquire_data), headers=headers)
            json_data = ""
            for i in resp.content:
                json_data += i.decode()
            json_data = ujson.loads(json_data)
            if json_data["code"] == 200:
                targetVersion = json_data["targetVersion"]
                url_zip = json_data["url"]
                fileMD5 = json_data["fileMd5"]
                action = json_data["action"]
                filesize = json_data["config"]["fileSize"]
                print("fileSize: ", filesize)
                print("targetVersion: ", targetVersion)
            else:
                action = json_data["action"]
                msg = json_data["msg"]
                code = json_data["code"]
                logger.info(msg)

            if action:
                report_url = "https://cloudota.quectel.com:8100/v1/fota/status/report"
                print("Please do not send instructions during the upgrade...")
                resp = request.get(url_zip)
                update_file = "dtu_handler_{}.py".format(targetVersion)
                f = open(usr + update_file, "wb+")
                count = 0
                for i in resp.content:
                    count += len(i)
                    f.write(i)
                    utime.sleep_ms(5)
                f.close()
                if filesize != count:
                    logger.info("Failed to download package data validation")
                    uos.remove(usr + "dtu_handler_V1.0.1.py")
                    #  模组状态及结果上报 升级失败，信息上报
                    data = self.data_info(version, imei, 8, "Update Failed")
                    request.post(report_url, data=ujson.dumps(data), headers=headers)
                    return
                #  模组状态及结果上报 升级成功，信息上报
                data = self.data_info(version, imei, 7, "upgrade success")
                resp = request.post(report_url, data=ujson.dumps(data), headers=headers)
                if resp.status_code == 200:
                    logger.info("The upgrade is completed and the information is reported successfully")
                else:
                    logger.info("Upgrade status information failed to be reported")
            ##################################################################################
            # 模组临终遗言信息上报
            if "system.log" not in uos.listdir(usr):
                logger.info("**********'system.log' not exist***********")
                logger.info("*********last will was not reported********")
                return
            with open(usr + "system.log", "r") as f:
                msg = f.read()
            Last_will_url = "https://cloudota.quectel.com:8100/v1/fota/msg/report"
            res = cellLocator.getLocation("www.queclocator.com", 80, "1111111122222222", 8, 1)
            data = {
                "imei": imei,
                "version": str(version),
                "signalStrength": net.csqQueryPoll(),
                "battery": 100,
                "latitude": res[0],
                "longitude": res[1],
                "details": "last will message report",
                "reportMsg": msg
            }
            headers = {"Content-Type": "application/json"}
            resp = request.post(Last_will_url, data=ujson.dumps(data), headers=headers)
            if resp.status_code == 200:
                logger.info("last will reported successfully")
            else:
                logger.info("last will was reported failed")
                return

    def data_info(self, version, imei, code, msg):
        data = {
            "version": version,
            "ver": "v1.0",
            "imei": imei,
            "code": code,
            "msg": msg
        }
        return data

    def server_filter(self):
        if self.parse_data.work_mode == 'command':
            for cid, channel in self.parse_data.conf.items():
                serial_id = int(channel.get("serialID"))
                if serial_id in self.channel.serial_channel_dict:
                    self.channel.serial_channel_dict[serial_id].append(cid)
                else:
                    self.channel.serial_channel_dict[serial_id] = [cid]
            return self.parse_data.conf
        else:
            serv_map = dict()
            serial_list = [0, 1, 2]
            for cid, channel in self.parse_data.conf.items():
                serial_id = int(channel.get("serialID"))
                if serial_id in serial_list:
                    serv_map[cid] = channel
                    self.channel.serial_channel_dict[serial_id] = [cid]
                    serial_list.remove(serial_id)
                else:
                    continue
            return serv_map

    def start(self):
        logger.info("parse data {}".format(self.parse_data.conf))
        reg_data = {"csq": net.csqQueryPoll(), "imei": modem.getDevImei(), "iccid": sim.getIccid(),
                    "ver": self.parse_data.version}  # 首次登陆服务器默认注册信息
        # 透传与modbus服务器筛选
        serv_maps = self.server_filter()
        self._serv_connect(serv_maps, reg_data)
        print("SERV conn success")
        _thread.start_new_thread(self.uart.read, ())
        if self.parse_data.offline_storage:
            _thread.start_new_thread(self.retry_offline_handler, ())

    def _serv_connect(self, serv_list, reg_data):
        for cid, data in serv_list.items():
            if not data:
                continue
            protocol = data.get('protocol').lower()
            self.cloud_protocol = protocol
            if protocol == "mqtt":
                dtu_mq = DtuMqttTransfer(self.uart)
                status = dtu_mq.serialize(data)
                try:
                    dtu_mq.connect()
                    _thread.start_new_thread(dtu_mq.wait, ())
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.MQTTERR), e))
                else:
                    if status == RET.OK:
                        self.channel.channel_dict[cid] = dtu_mq
                        dtu_mq.channel_id = cid
                        print("mqtt conn succeed")
                    else:
                        logger.error(error_map.get(RET.MQTTERR))

            elif protocol == "aliyun":
                dtu_ali = ALYDtuMqttTransfer(self.uart)
                status = dtu_ali.serialize(data)
                try:
                    _thread.start_new_thread(dtu_ali.connect, ())
                    utime.sleep_ms(100)
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.ALIYUNMQTTERR), e))
                else:
                    if status == RET.OK:
                        self.channel.channel_dict[cid] = dtu_ali
                        dtu_ali.channel_id = cid
                        print("aliyun conn succeed")
                    else:
                        logger.error(error_map.get(RET.ALIYUNMQTTERR))

            elif protocol == "txyun":
                dtu_txy = TXYDtuMqttTransfer(self.uart)
                status = dtu_txy.serialize(data)
                try:
                    _thread.start_new_thread(dtu_txy.connect, ())
                    utime.sleep_ms(100)
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.TXYUNMQTTERR), e))
                else:
                    if status == RET.OK:
                        self.channel.channel_dict[cid] = dtu_txy
                        dtu_txy.channel_id = cid
                        print("txyun conn succeed")
                    else:
                        logger.error(error_map.get(RET.TXYUNMQTTERR))

            elif protocol == "tcp":
                tcp_sock = TcpSocket(self.uart)
                status = tcp_sock.serialize(data)
                try:
                    tcp_sock.connect()
                    _thread.start_new_thread(tcp_sock.recv, ())
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.TCPERR), e))
                else:
                    if status == RET.OK:
                        if self.parse_data.reg == 1:
                            tcp_sock.first_reg(reg_data)
                            logger.info("TCP send first login information {}".format(reg_data))
                        if data.get("ping"):
                            if int(data.get('heartbeat')) != 0:
                                _thread.start_new_thread(tcp_sock.Heartbeat, ())
                        self.channel.channel_dict[cid] = tcp_sock
                        tcp_sock.channel_id = cid
                    else:
                        logger.error(error_map.get(RET.TCPERR))

            elif protocol == "udp":
                udp_sock = UdpSocket()
                status = udp_sock.serialize(data)
                try:
                    udp_sock.connect(self.uart)
                    _thread.start_new_thread(udp_sock.recv, ())
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.UDPERR), e))
                else:
                    if status == RET.OK:
                        if self.parse_data.reg == 1:
                            udp_sock.first_reg(reg_data)
                            logger.info("UDP send first login information {}".format(reg_data))
                        if data.get("ping"):
                            if int(data.get('heartbeat')) != 0:
                                _thread.start_new_thread(udp_sock.Heartbeat, ())
                        self.channel.channel_dict[cid] = udp_sock
                        udp_sock.channel_id = cid
                    else:
                        logger.error(error_map.get(RET.UDPERR))

            elif protocol.startswith("http"):
                dtu_req = DtuRequest(self.uart)
                status = dtu_req.serialize(data)
                if status == RET.OK:
                    data = dtu_req.req()  # 发送请求
                    print("***********************http request***********************")
                    for i in data:
                        print(i)
                    self.channel.channel_dict[cid] = dtu_req
                    dtu_req.channel_id = cid
                else:
                    logger.error(error_map.get(RET.HTTPERR))
            elif protocol.startswith("quecthing"):
                quec_req = QuecthingDtuTransfer(self.uart)
                status = quec_req.serialize(data)
                try:
                    _thread.start_new_thread(quec_req.connect, ())
                    utime.sleep_ms(100)
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.QUECIOTERR), e))
                else:
                    if status == RET.OK:
                        self.channel.channel_dict[cid] = quec_req
                        quec_req.channel_id = cid
                        print("quecthing connect waiting server...")
                    else:
                        logger.error(error_map.get(RET.QUECIOTERR))

            elif protocol.startswith("hwyun"):
                hw_req = HuaweiCloudTransfer(self.uart)
                status = hw_req.serialize(data)
                try:
                    _thread.start_new_thread(hw_req.connect, ())
                    utime.sleep_ms(100)
                except Exception as e:
                    logger.error("{}: {}".format(error_map.get(RET.HWYUNERR), e))
                else:
                    if status == RET.OK:
                        self.channel.channel_dict[cid] = hw_req
                        hw_req.channel_id = cid
                        print("hwyun conn succeed")
                    else:
                        logger.error(error_map.get(RET.HWYUNERR))
            else:
                continue

    def _run(self):
        # try:
        self.prepare()
        print("prepart ready")

        self.parse()
        print("dialing parse")

        self.dialing()
        print("dialing ready")
        
        self.request()
        print("dialing request")
        self.start()
        # except Exception as e:
        #     print(e)
            # 加载bak文件
        # else:
        #     while 1:
        #         pass

    def refresh(self):
        print("refresh start")
        print(self.parse_data.auto_connect)
        if self.parse_data.auto_connect:
            print("refresh run")
            try:
                self._run()
            except Exception as e:
                print(e)
                print("Switch to backup file")
                CONFIG['config_path'] = CONFIG['config_path'] + ".bak"
                # 尝试加载备份config
                try:
                    self._run()
                except Exception as e:
                    print(e)
                    print("Switch to default file")
                    CONFIG['config_path'] = CONFIG['config_default_path']
                    # 尝试加载默认config
                    try:
                        self._run()
                    except Exception as e:
                        print(e)
                        print("default config load failed.")
        # else:
        #     pass

    def retry_offline_handler(self):
        while True:
            for code, channel in self.channels.channel_dict.items():
                has_msg = self.off_storage.channel_has_msg(code)
                if has_msg:
                    msg = self.off_storage.take_out(code)
                    for m in msg:
                        channel.send(m)
                else:
                    continue
            utime.sleep(20)
@Singleton
class ProdGPIO(object):
    def __init__(self, pins):
        # self.gpio1 = Pin(Pin.GPIO1, Pin.OUT, Pin.PULL_DISABLE, 0)
        set_gpio = False
        print("pin: ", pins)
        for i in pins:
            if len(i):
                try:
                    gpio = int(i)
                except:
                    logger.error("dtu_config.json pins setting error! Only allow numbers")
                    continue
                print("gpio {} set".format(gpio))
                gpio_n = getattr(Pin, 'GPIO%d' % gpio)
                gpio_obj = Pin(gpio_n, Pin.OUT, Pin.PULL_DISABLE, 0)
                setattr(self, "gpio%d" % gpio, gpio_obj)
                set_gpio = True

        if not set_gpio:
            self.gpio1 = Pin(Pin.GPIO1, Pin.OUT, Pin.PULL_DISABLE, 0)

    def status(self):
        self.gpio1.read()

    def show(self):
        self.gpio1.write(1)


"""=================================================== run ============================================================"""


def run():

    config_params = ProdDocumentParse().refresh_document(CONFIG["config_path"])

    dtu = ProdDtu()

    dtu.set_gpio(ProdGPIO(ujson.loads(config_params)["pins"]))

    dtu.set_uart(DtuUart(config_params))

    dtu.set_parse_data(DTUDocumentData())

    dtu.set_document_parser(ProdDocumentParse())
    
    dtu.set_channels(ChannelTransfer())

    dtu.set_off_storage(OfflineStorage())
    
    dtu.refresh()


if __name__ == '__main__':
    run()

