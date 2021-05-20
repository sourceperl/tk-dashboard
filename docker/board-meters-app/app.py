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
LTX_IP = '192.168.0.62'
# modbus address for IEM 3155 and 2155
AD_3155_LIVE_PWR = 3059
AD_2155_LIVE_PWR = 3053
AD_3155_INDEX_PWR = 3205
AD_2155_INDEX_PWR = 3205

# read config
cnf = ConfigParser()
cnf.read('/data/board-conf-vol/dashboard.conf')
# thingspeak api key
ts_pwr_api_key = cnf.get('electric_meter', 'tspeak_pwr_w_key')
ts_idx_api_key = cnf.get('electric_meter', 'tspeak_idx_w_key')


class Devices(object):
    # redis datasource
    rd = RedisDevice()
    # modbus datasource
    # meter 'garage'
    meter_garage = ModbusTCPDevice(LTX_IP, timeout=2.0, refresh=2.0, unit_id=1)
    meter_garage.add_floats_table(AD_3155_LIVE_PWR)
    meter_garage.add_longs_table(AD_3155_INDEX_PWR)
    # meter 'cold water'
    meter_cold_water = ModbusTCPDevice(LTX_IP, timeout=2.0, refresh=2.0, unit_id=2)
    meter_cold_water.add_floats_table(AD_3155_LIVE_PWR)
    meter_cold_water.add_longs_table(AD_3155_INDEX_PWR)
    # meter 'light'
    meter_light = ModbusTCPDevice(LTX_IP, timeout=2.0, refresh=2.0, unit_id=3)
    meter_light.add_floats_table(AD_3155_LIVE_PWR)
    meter_light.add_longs_table(AD_3155_INDEX_PWR)
    # meter 'tech'
    meter_tech = ModbusTCPDevice(LTX_IP, timeout=2.0, refresh=2.0, unit_id=4)
    meter_tech.add_floats_table(AD_3155_LIVE_PWR)
    meter_tech.add_longs_table(AD_3155_INDEX_PWR)
    # meter 'CTA' (air process)
    meter_cta = ModbusTCPDevice(LTX_IP, timeout=2.0, refresh=2.0, unit_id=5)
    meter_cta.add_floats_table(AD_3155_LIVE_PWR)
    meter_cta.add_longs_table(AD_3155_INDEX_PWR)
    # meter 'heater room'
    meter_heat = ModbusTCPDevice(LTX_IP, timeout=2.0, refresh=2.0, unit_id=6)
    meter_heat.add_floats_table(AD_2155_LIVE_PWR)
    meter_heat.add_longs_table(AD_2155_INDEX_PWR)


class Tags(object):
    # redis tags
    RD_TOTAL_PWR = Tag(0, src=Devices.rd, ref={'type': 'int',
                                               'key': 'meters:electric:site:pwr_act',
                                               'ttl': 60})
    RD_TODAY_WH = Tag(0.0, src=Devices.rd, ref={'type': 'float',
                                                'key': 'meters:electric:site:today_wh',
                                                'ttl': 86400})
    RD_YESTERDAY_WH = Tag(0.0, src=Devices.rd, ref={'type': 'float',
                                                    'key': 'meters:electric:site:yesterday_wh',
                                                    'ttl': 172800})
    RD_TIMESTAMP_WH = Tag(0.0, src=Devices.rd, ref={'type': 'float',
                                                    'key': 'meters:electric:site:timestamp_wh',
                                                    'ttl': 172800})
    # modbus tags
    GARAGE_PWR = Tag(0.0, src=Devices.meter_garage, ref={'type': 'float', 'addr': AD_3155_LIVE_PWR, 'span': 1000})
    GARAGE_I_PWR = Tag(0, src=Devices.meter_garage, ref={'type': 'long', 'addr': AD_3155_INDEX_PWR, 'span': 1 / 1000})
    COLD_WATER_PWR = Tag(0.0, src=Devices.meter_cold_water, ref={'type': 'float', 'addr': AD_3155_LIVE_PWR, 'span': 1000})
    COLD_WATER_I_PWR = Tag(0, src=Devices.meter_cold_water, ref={'type': 'long', 'addr': AD_3155_INDEX_PWR, 'span': 1 / 1000})
    LIGHT_PWR = Tag(0.0, src=Devices.meter_light, ref={'type': 'float', 'addr': AD_3155_LIVE_PWR, 'span': 1000})
    LIGHT_I_PWR = Tag(0, src=Devices.meter_light, ref={'type': 'long', 'addr': AD_3155_INDEX_PWR, 'span': 1 / 1000})
    TECH_PWR = Tag(0.0, src=Devices.meter_tech, ref={'type': 'float', 'addr': AD_3155_LIVE_PWR, 'span': 1000})
    TECH_I_PWR = Tag(0, src=Devices.meter_tech, ref={'type': 'long', 'addr': AD_3155_INDEX_PWR, 'span': 1 / 1000})
    CTA_PWR = Tag(0.0, src=Devices.meter_cta, ref={'type': 'float', 'addr': AD_3155_LIVE_PWR, 'span': 1000})
    CTA_I_PWR = Tag(0, src=Devices.meter_cta, ref={'type': 'long', 'addr': AD_3155_INDEX_PWR, 'span': 1 / 1000})
    HEAT_PWR = Tag(0.0, src=Devices.meter_heat, ref={'type': 'float', 'addr': AD_2155_LIVE_PWR, 'span': 1000})
    HEAT_I_PWR = Tag(0.0, src=Devices.meter_heat, ref={'type': 'long', 'addr': AD_2155_INDEX_PWR, 'span': 1 / 1000})
    # virtual tags
    # total power consumption
    TOTAL_PWR = Tag(0.0, get_cmd=lambda: Tags.GARAGE_PWR.val + Tags.COLD_WATER_PWR.val +
                                         Tags.LIGHT_PWR.val + Tags.TECH_PWR.val +
                                         Tags.CTA_PWR.val + Tags.HEAT_PWR.val)


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
    d_data = {'api_key': api_key}
    for i, value in enumerate(l_values):
        i += 1
        d_data['field%i' % i] = value
    # try loop
    while True:
        if req_try <= 0:
            break
        else:
            req_try -= 1
        try:
            r = requests.post('https://api.thingspeak.com/update', data=d_data, timeout=10.0)
            logging.debug('thingspeak_send: POST data %s' % d_data)
        except Exception:
            logging.error(traceback.format_exc())
            pass
        else:
            is_ok = ((r.status_code == 200) and (int(r.text) != 0))
            logging.debug('thingspeak_send: status: %s' % ('ok' if is_ok else 'error'))
            break
    return is_ok


def db_refresh_job():
    since_last_integrate = time.time() - Tags.RD_TIMESTAMP_WH.val
    Tags.RD_TIMESTAMP_WH.val += since_last_integrate
    # integrate active power for daily index (if time since last integrate is regular)
    if 0 < since_last_integrate < 7200:
        Tags.RD_TODAY_WH.val += Tags.TOTAL_PWR.val * since_last_integrate / 3600
    # publish active power
    Tags.RD_TOTAL_PWR.val = Tags.TOTAL_PWR.e_val


def db_midnight_job():
    # backup daily value to yesterday then reset it for new day start
    Tags.RD_YESTERDAY_WH.val = Tags.RD_TODAY_WH.val
    Tags.RD_TODAY_WH.val = 0


def web_publish_pwr_job():
    l_fields = (
        round(Tags.TOTAL_PWR.val),
        round(Tags.GARAGE_PWR.val),
        round(Tags.COLD_WATER_PWR.val),
        round(Tags.LIGHT_PWR.val),
        round(Tags.TECH_PWR.val),
        round(Tags.CTA_PWR.val),
        round(Tags.HEAT_PWR.val),
    )
    thingspeak_send(api_key=ts_pwr_api_key, l_values=l_fields)


def web_publish_index_job():
    l_fields = (
        round(Tags.GARAGE_I_PWR.val),
        round(Tags.COLD_WATER_I_PWR.val),
        round(Tags.LIGHT_I_PWR.val),
        round(Tags.TECH_I_PWR.val),
        round(Tags.CTA_I_PWR.val),
        round(Tags.HEAT_I_PWR.val),
    )
    thingspeak_send(api_key=ts_idx_api_key, l_values=l_fields)


if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('board-meters-app started')

    # wait DS_ModbusTCP thread start
    time.sleep(1.0)

    # init scheduler
    schedule.every(5).seconds.do(db_refresh_job)
    schedule.every().day.at('00:00').do(db_midnight_job)
    schedule.every(2).minutes.do(web_publish_pwr_job)
    schedule.every().day.at('06:00').do(web_publish_index_job)
    # first call
    db_refresh_job()
    web_publish_pwr_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1.0)
