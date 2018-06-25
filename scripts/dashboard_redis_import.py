#!/usr/bin/env python3

from collections import OrderedDict
from configparser import ConfigParser
from datetime import datetime, timedelta
import feedparser
import json
import logging
import os
import time
import traceback
from bs4 import BeautifulSoup
import redis
import requests
import schedule
import shutil
import urllib.parse
import pytz
from xml.dom import minidom

# read config
cnf = ConfigParser()
cnf.read(os.path.expanduser('~/.dashboard_config'))
# gsheet
gsheet_url = cnf.get('gsheet', 'url')
# openweathermap
ow_app_id = cnf.get('openweathermap', 'app_id')
ow_city = cnf.get('openweathermap', 'city')
# iswip
iswip_url = cnf.get('iswip', 'url')
# gmap (traffic duration)
gmap_key = cnf.get('gmap', 'key')
gmap_origin = cnf.get('gmap', 'origin')
# gmap img traffic
gmap_img_url = cnf.get("gmap_img", "img_url")
gmap_img_target = cnf.get("gmap_img", "img_target")


# dataset access
class DS:
    # create connector
    r = redis.StrictRedis(host="192.168.0.60", socket_timeout=5, socket_keepalive=True)

    # redis access method
    @classmethod
    def redis_set(cls, name, value):
        try:
            return cls.r.set(name, value)
        except redis.RedisError:
            return None

    @classmethod
    def redis_set_obj(cls, name, obj):
        try:
            return cls.r.set(name, json.dumps(obj))
        except (redis.RedisError, AttributeError, json.decoder.JSONDecodeError):
            return None


# some function
def gsheet_job():
    # https request
    try:
        response = requests.get(gsheet_url)
    except requests.exceptions.RequestException:
        logging.error(traceback.format_exc())
        return None
    # process response
    try:
        d = dict()
        for line in response.iter_lines(decode_unicode='utf-8'):
            tag, value = line.split(',')
            d[tag] = value
        d['UPDATE'] = datetime.now().isoformat("T")
        DS.redis_set_obj("gsheet:grt", d)
    except Exception:
        logging.error(traceback.format_exc())


def openweathermap_job():
    # https request
    try:
        ow_url = "http://api.openweathermap.org/data/2.5/forecast?q=%s&appid=%s&units=metric&lang=fr" % (ow_city, ow_app_id)
        ow_d = requests.get(ow_url).json()
    except requests.exceptions.RequestException:
        logging.error(traceback.format_exc())
        return None
    # decode json
    try:
        # init struct
        t_today = None
        d_days = {}
        for i in range(0, 5):
            d_days[i] = dict(t_min=50.0, t_max=-50.0, main='', description='', icon='')
        # parse json
        for item in ow_d["list"]:
            # for day-0 to day-4
            for i_day in range(5):
                txt_date, txt_time = item['dt_txt'].split(' ')
                # search today
                if txt_date == (datetime.now() + timedelta(days=i_day)).date().strftime('%Y-%m-%d'):
                    # search min/max temp
                    d_days[i_day]['t_min'] = min(d_days[i_day]['t_min'], item['main']['temp_min'])
                    d_days[i_day]['t_max'] = max(d_days[i_day]['t_max'], item['main']['temp_max'])
                    # main and icon in 12h item
                    if txt_time == '12:00:00' or t_today is None:
                        d_days[i_day]['main'] = item['weather'][0]['main']
                        d_days[i_day]['icon'] = item['weather'][0]['icon']
                        d_days[i_day]['description'] = item['weather'][0]['description']
                        if t_today is None:
                            t_today = item['main']['temp']
                            d_days[0]['t'] = t_today
        # store to redis
        city_name, _ = ow_city.split(',')
        DS.redis_set_obj('weather:forecast:%s' % city_name.lower(), d_days)
    except Exception:
        logging.error(traceback.format_exc())


def vigilance_job():
    try:
        # request XML data from server
        r = requests.get('http://vigilance.meteofrance.com/data/NXFR34_LFPW_.xml')
        # check error
        if r.status_code == 200:
            # dom parsing (convert UTF-8 r.text to XML char)
            dom = minidom.parseString(r.text.encode('ascii', 'xmlcharrefreplace'))
            # set dict for dep data
            vig_data = {'update': "", 'department': {}}
            # map build date
            tz = pytz.timezone('Europe/Paris')
            map_date = str(dom.getElementsByTagName('entetevigilance')[0].getAttribute('dateinsert'))
            map_dt = tz.localize(datetime(int(map_date[0:4]), int(map_date[4:6]),
                                          int(map_date[6:8]), int(map_date[8:10]),
                                          int(map_date[10:12])))
            vig_data['update'] = map_dt.isoformat()
            # parse every departments
            for items in dom.getElementsByTagName('datavigilance'):
                # current "department"
                dep_code = str(items.attributes['dep'].value)
                # get risk ID  if exist
                risk_id = None
                for risk in items.getElementsByTagName('risque'):
                    risk_id = int(risk.attributes['valeur'].value)
                # get flood ID if exist
                flood_id = None
                for flood in items.getElementsByTagName('crue'):
                    flood_id = int(flood.attributes['valeur'].value)
                # get color ID
                color_id = int(items.attributes['couleur'].value)
                # build vig_data
                vig_data['department'][dep_code] = {'vig_level': color_id,
                                                    'flood_level': flood_id,
                                                    'risk_id': risk_id}
            DS.redis_set_obj('weather:vigilance', vig_data)
    except Exception:
        logging.error(traceback.format_exc())


def iswip_job():
    # https request
    try:
        devices_l = requests.get(iswip_url).json()
    except requests.exceptions.RequestException:
        logging.error(traceback.format_exc())
        return None
    # decode json
    try:
        d_dev = {}
        for device in devices_l:
            # device id
            dev_id = str(device['device_description']).replace(' ', '_')
            # device message
            dev_msg = ''
            for token in device['lastmessage_content'].split(';'):
                name, value = token.split('=')
                if name == 'TypeMessage':
                    dev_msg = value
            # update redis
            d_dev[dev_id] = dev_msg
        DS.redis_set_obj('iswip:room_status', d_dev)
    except Exception:
        logging.error(traceback.format_exc())


def local_info_job():
    # http request
    try:
        l_titles = []
        for post in feedparser.parse('https://france3-regions.francetvinfo.fr/societe/rss?r=hauts-de-france').entries:
            l_titles.append(post.title)
        DS.redis_set_obj('news:local', l_titles)
    except Exception:
        logging.error(traceback.format_exc())


def gmap_travel_time_job():
    d_traffic = {}
    for gm_dest in ("Arras", "Amiens", "Dunkerque", "Maubeuge", "Reims"):
        # build url
        gm_url_origin = urllib.parse.quote_plus(gmap_origin)
        gm_url_destination = urllib.parse.quote_plus(gm_dest)
        gm_url = "https://maps.googleapis.com/maps/api/directions/json"
        gm_url += "?&origin=%s&destination=%s&departure_time=now&key=%s"
        gm_url %= gm_url_origin, gm_url_destination, gmap_key
        # http request
        try:
            gm_json = requests.get(gm_url).json()
        except requests.exceptions.RequestException:
            logging.error(traceback.format_exc())
            return None
        # decode json
        try:
            duration_abs = gm_json["routes"][0]["legs"][0]["duration"]["value"]
            duration_with_traffic = gm_json["routes"][0]["legs"][0]["duration_in_traffic"]["value"]
            d_traffic[gm_dest] = dict(duration=duration_abs, duration_traffic=duration_with_traffic)
        except Exception:
            logging.error(traceback.format_exc())
    DS.redis_set_obj('gmap:traffic', d_traffic)


def sport_l1_job():
    # http request
    try:
        r = requests.get("http://m.lfp.fr/ligue1/classement")

        if r.status_code == 200:
            od_l1_club = OrderedDict()
            s = BeautifulSoup(r.content, "html.parser")

            # first table on page
            t = s.find_all("table")[0]

            # each row in table
            for row in t.find_all("tr"):
                name = row.find("td", attrs={"class": "club"})
                if name:
                    # club name as dict key
                    name = name.text.strip()
                    od_l1_club[name] = OrderedDict()
                    # find rank
                    od_l1_club[name]['rank'] = row.find("td").text.strip()
                    # find points
                    od_l1_club[name]['pts'] = row.find("td", attrs={"class": "pts"}).text.strip()
                    # find all stats
                    l_td_center = row.find_all("td", attrs={"class": "center"})
                    if l_td_center:
                        od_l1_club[name]["played"] = l_td_center[0].text.strip()
                        od_l1_club[name]["wins"] = l_td_center[1].text.strip()
                        od_l1_club[name]["draws"] = l_td_center[2].text.strip()
                        od_l1_club[name]["loses"] = l_td_center[3].text.strip()
                        od_l1_club[name]["for"] = l_td_center[4].text.strip()
                        od_l1_club[name]["against"] = l_td_center[5].text.strip()
                        od_l1_club[name]["diff"] = l_td_center[6].text.strip()
            DS.redis_set_obj('sport:l1', od_l1_club)
    except requests.exceptions.RequestException:
        logging.error(traceback.format_exc())
        return None


def gmap_traffic_img_job():
    # http request
    try:
        r = requests.get(gmap_img_url, stream=True)
        if r.status_code == 200:
            # download as *.dwl file
            download_file = "%s.dwl" % gmap_img_target
            with open(download_file, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
            # replace target file with *.dwl version
            shutil.move(download_file, gmap_img_target)
    except requests.exceptions.RequestException:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')

    # init scheduler
    schedule.every(1).minute.do(iswip_job)
    schedule.every(2).minutes.do(gmap_traffic_img_job)
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(5).minutes.do(openweathermap_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(5).minutes.do(gmap_travel_time_job)
    schedule.every(30).minutes.do(sport_l1_job)
    # first call
    gmap_traffic_img_job()
    gsheet_job()
    openweathermap_job()
    vigilance_job()
    local_info_job()
    iswip_job()
    gmap_travel_time_job()
    sport_l1_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)
