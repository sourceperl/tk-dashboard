#!/usr/bin/env python3

from configparser import ConfigParser
import logging
import os
import time
import traceback
from pyHMI.DS_ModbusTCP import ModbusTCPDevice
from pyHMI.DS_Redis import RedisDevice
from pyHMI.Tag import Tag
import requests
import schedule

# some const
# modbus address for IEM 3155 and 2155
AD_3155_ACT_PWR = 3059
AD_2155_ACT_PWR = 3053

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# hostname of master dashboard
dash_master_host = cnf.get("dashboard", "master_host")
# thingspeak api key
ts_api_key = cnf.get("electric_meter", "thingspeak_write_key")


class Devices(object):
    # redis datasource
    rd = RedisDevice(host=dash_master_host)
    # modbus datasource
    # meter "garage"
    meter_garage = ModbusTCPDevice('192.168.0.62', timeout=2.0, refresh=2.0, unit_id=1)
    meter_garage.add_floats_table(AD_3155_ACT_PWR)
    # meter "cold water"
    meter_cold_water = ModbusTCPDevice('192.168.0.62', timeout=2.0, refresh=2.0, unit_id=2)
    meter_cold_water.add_floats_table(AD_3155_ACT_PWR)
    # meter "light"
    meter_light = ModbusTCPDevice('192.168.0.62', timeout=2.0, refresh=2.0, unit_id=3)
    meter_light.add_floats_table(AD_3155_ACT_PWR)
    # meter "tech"
    meter_tech = ModbusTCPDevice('192.168.0.62', timeout=2.0, refresh=2.0, unit_id=4)
    meter_tech.add_floats_table(AD_3155_ACT_PWR)
    # meter "CTA" (air process)
    meter_cta = ModbusTCPDevice('192.168.0.62', timeout=2.0, refresh=2.0, unit_id=5)
    meter_cta.add_floats_table(AD_3155_ACT_PWR)
    # meter "heater room"
    meter_heat = ModbusTCPDevice('192.168.0.62', timeout=2.0, refresh=2.0, unit_id=6)
    meter_heat.add_floats_table(AD_2155_ACT_PWR)


class Tags(object):
    # redis tags
    RD_TOTAL_P_ACT = Tag(0, src=Devices.rd, ref={'type': 'int',
                                                 'key': 'meters:electric:site:pwr_act',
                                                 'ttl': 60})
    # modbus tags
    GARAGE_P_ACT = Tag(0.0, src=Devices.meter_garage, ref={'type': 'float', 'addr': AD_3155_ACT_PWR, 'span': 1000})
    COLD_WATER_P_ACT = Tag(0.0, src=Devices.meter_cold_water,
                           ref={'type': 'float', 'addr': AD_3155_ACT_PWR, 'span': 1000})
    LIGHT_P_ACT = Tag(0.0, src=Devices.meter_light, ref={'type': 'float', 'addr': AD_3155_ACT_PWR, 'span': 1000})
    TECH_P_ACT = Tag(0.0, src=Devices.meter_tech, ref={'type': 'float', 'addr': AD_3155_ACT_PWR, 'span': 1000})
    CTA_P_ACT = Tag(0.0, src=Devices.meter_cta, ref={'type': 'float', 'addr': AD_3155_ACT_PWR, 'span': 1000})
    HEAT_P_ACT = Tag(0.0, src=Devices.meter_heat, ref={'type': 'float', 'addr': AD_2155_ACT_PWR, 'span': 1000})
    # virtual tags
    # total power consumption
    TOTAL_P_ACT = Tag(0.0, get_cmd=lambda: Tags.GARAGE_P_ACT.val + Tags.COLD_WATER_P_ACT.val +
                                           Tags.LIGHT_P_ACT.val + Tags.TECH_P_ACT.val +
                                           Tags.CTA_P_ACT.val + Tags.HEAT_P_ACT.val)


def thingspeak_send(api_key, l_values=list()):
    """ upload data to thingspeak platform
    :param api_key: thingspeak write API Key
    :type api_key: str
    :param l_values: value to update as a list (map to field1, field2...)
    :type l_values: list or tuple
    :return: True if update is a success, False otherwise
    :rtype: bool
    """
    req_try = 3
    is_ok = False
    # format data for post request
    d_data = {"api_key": api_key}
    for i, value in enumerate(l_values):
        i += 1
        d_data["field%i" % i] = value
    # try loop
    while True:
        if req_try <= 0:
            break
        else:
            req_try -= 1
        try:
            r = requests.post('https://api.thingspeak.com/update', data=d_data, timeout=5.0)
            logging.debug("thingspeak_send: POST data %s" % d_data)
        except Exception:
            logging.error(traceback.format_exc())
            pass
        else:
            is_ok = ((r.status_code == 200) and (int(r.text) != 0))
            logging.debug("thingspeak_send: status: %s" % ("ok" if is_ok else "error"))
            break
    return is_ok


def redis_job():
    Tags.RD_TOTAL_P_ACT.val = Tags.TOTAL_P_ACT.e_val


def thingspeak_job():
    l_fields = (
        round(Tags.TOTAL_P_ACT.val),
        round(Tags.GARAGE_P_ACT.val),
        round(Tags.COLD_WATER_P_ACT.val),
        round(Tags.LIGHT_P_ACT.val),
        round(Tags.TECH_P_ACT.val),
        round(Tags.CTA_P_ACT.val),
        round(Tags.HEAT_P_ACT.val),
    )
    thingspeak_send(api_key=ts_api_key, l_values=l_fields)


if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # wait DS_ModbusTCP thread start
    time.sleep(1.0)

    # init scheduler
    schedule.every(5).seconds.do(redis_job)
    schedule.every(2).minutes.do(thingspeak_job)
    # first call
    redis_job()
    thingspeak_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1.0)
