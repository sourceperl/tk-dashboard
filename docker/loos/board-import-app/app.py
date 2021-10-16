#!/usr/bin/env python3

import base64
from collections import Counter
from configparser import ConfigParser
from datetime import datetime, timedelta
import math
import secrets
import urllib.parse
import html
import json
import logging
import functools
import io
import re
import time
from xml.dom import minidom
import zlib
import feedparser
import redis
import requests
from requests_oauthlib import OAuth1
import schedule
import PIL.Image
from wordcloud import WordCloud
from metar.Metar import Metar
import pytz

# some const
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1'

# read config
cnf = ConfigParser()
cnf.read('/data/conf/dashboard.conf')
# hostname of bridge server
bridge_host = cnf.get('bridge', 'bridge_host')
# gmap img traffic
gmap_img_url = cnf.get('gmap_img', 'img_url')
# gsheet
gsheet_url = cnf.get('gsheet', 'url')
# openweathermap
ow_app_id = cnf.get('openweathermap', 'app_id')
# twitter
tw_api_key = cnf.get('twitter', 'api_key')
tw_api_secret = cnf.get('twitter', 'api_secret')
tw_access_token = cnf.get('twitter', 'access_token')
tw_access_token_secret = cnf.get('twitter', 'access_token_secret')
# dweet
dweet_id = cnf.get('dweet', 'id')
dweet_key = cnf.get('dweet', 'key')


# some functions
def catch_log_except(catch=None, log_lvl=logging.ERROR, limit_arg_len=40):
    # decorator to catch exception and produce one line log message
    if catch is None:
        catch = Exception

    def _catch_log_except(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except catch as e:
                # format function call "f_name(args..., kwargs...)" string (with arg/kwargs len limit)
                func_args = ''
                for arg in args:
                    func_args += ', ' if func_args else ''
                    func_args += repr(arg) if len(repr(arg)) < limit_arg_len else repr(arg)[:limit_arg_len - 2] + '..'
                for k, v in kwargs.items():
                    func_args += ', ' if func_args else ''
                    func_args += repr(k) + '='
                    func_args += repr(v) if len(repr(v)) < limit_arg_len else repr(v)[:limit_arg_len - 2] + '..'
                func_call = f'{func.__name__}({func_args})'
                # log message "except [except class] in f_name(args..., kwargs...): [except msg]"
                logging.log(log_lvl, f'except {type(e)} in {func_call}: {e}')

        return wrapper

    return _catch_log_except


def dt_utc_to_local(utc_dt):
    now_ts = time.time()
    offset = datetime.fromtimestamp(now_ts) - datetime.utcfromtimestamp(now_ts)
    return utc_dt + offset


def byte_xor(bytes_1, bytes_2):
    return bytes([_a ^ _b for _a, _b in zip(bytes_1, bytes_2)])


def dweet_encode(bytes_data):
    # compress data
    c_data = zlib.compress(bytes_data)
    # generate a random token
    token = secrets.token_bytes(64)
    # xor random token and private key
    key = dweet_key.encode('utf8')
    key_mask = key * math.ceil(len(token) / len(key))
    xor_token = byte_xor(token, key_mask)
    # xor data and token
    token_mask = token * math.ceil(len(c_data) / len(token))
    xor_data = byte_xor(c_data, token_mask)
    # concatenate xor random token and xor data
    msg_block = xor_token + xor_data
    # encode result in base64 (for no utf-8 byte support)
    return base64.b64encode(msg_block)


def dweet_decode(b64_msg_block):
    # decode base64 msg
    msg_block = base64.b64decode(b64_msg_block)
    # split message: [xor_token part : xor_data part]
    xor_token = msg_block[:64]
    xor_data = msg_block[64:]
    # token = xor_token xor private key
    key = dweet_key.encode('utf8')
    key_mask = key * math.ceil(len(xor_token) / len(key))
    token = byte_xor(xor_token, key_mask)
    # compressed data = xor_data xor token
    token_mask = token * math.ceil(len(xor_data) / len(token))
    c_data = byte_xor(xor_data, token_mask)
    # return decompress data
    return zlib.decompress(c_data)


# some class
class CustomRedis(redis.StrictRedis):
    @catch_log_except(catch=redis.RedisError)
    def set_ttl(self, name, ttl=3600):
        return self.expire(name, ttl)

    @catch_log_except(catch=redis.RedisError)
    def set_bytes(self, name, value):
        return self.set(name, value)

    @catch_log_except(catch=redis.RedisError)
    def get_bytes(self, name):
        return self.get(name)

    @catch_log_except(catch=redis.RedisError)
    def set_str(self, name, value):
        return self.set(name, value)

    @catch_log_except(catch=(redis.RedisError, AttributeError))
    def get_str(self, name):
        return self.get(name).decode('utf-8')

    @catch_log_except(catch=(redis.RedisError, AttributeError, json.decoder.JSONDecodeError))
    def set_to_json(self, name, obj):
        return self.set(name, json.dumps(obj))

    @catch_log_except(catch=(redis.RedisError, AttributeError, json.decoder.JSONDecodeError))
    def get_from_json(self, name):
        return json.loads(self.get(name).decode('utf-8'))


class DB:
    # create connector
    master = CustomRedis(host='board-redis-srv', socket_timeout=4, socket_keepalive=True)
    bridge = CustomRedis(host=bridge_host, socket_timeout=4, socket_keepalive=True)


# some function
@catch_log_except()
def air_quality_atmo_hdf_job():
    url = 'https://services8.arcgis.com/' + \
          'rxZzohbySMKHTNcy/arcgis/rest/services/ind_hdf_3j/FeatureServer/0/query' + \
          '?where=%s' % urllib.parse.quote('code_zone IN (02691, 59183, 59350, 59392, 59606, 80021)') + \
          '&outFields=date_ech, code_qual, lib_qual, lib_zone, code_zone' + \
          '&returnGeometry=false&resultRecordCount=48' + \
          '&orderByFields=%s&f=json' % urllib.parse.quote('date_ech DESC')
    today_dt_date = datetime.today().date()
    # https request
    r = requests.get(url, timeout=5.0)
    # check error
    if r.status_code == 200:
        # decode json message
        atmo_raw_d = r.json()
        # populate zones dict with receive values
        zones_d = {}
        for record in atmo_raw_d['features']:
            # load record data
            r_code_zone = record['attributes']['code_zone']
            r_ts = int(record['attributes']['date_ech'])
            r_dt = datetime.utcfromtimestamp(r_ts / 1000)
            r_value = record['attributes']['code_qual']
            # retain today value
            if r_dt.date() == today_dt_date:
                zones_d[r_code_zone] = r_value
        # skip key publish if zones_d is empty
        if not zones_d:
            raise ValueError('dataset is empty')
        # create and populate result dict
        d_air_quality = {'amiens': zones_d.get('80021', 0),
                         'dunkerque': zones_d.get('59183', 0),
                         'lille': zones_d.get('59350', 0),
                         'maubeuge': zones_d.get('59392', 0),
                         'saint-quentin': zones_d.get('02691', 0),
                         'valenciennes': zones_d.get('59606', 0)}
        # update redis
        DB.master.set_to_json('atmo:quality', d_air_quality)
        DB.master.set_ttl('atmo:quality', ttl=6 * 3600)


@catch_log_except()
def bridge_job():
    # relay flyspray data from bridge to master DB
    fly_data_nord = DB.bridge.get_from_json('rx:bur:flyspray_rss_nord')
    fly_data_est = DB.bridge.get_from_json('rx:bur:flyspray_rss_est')
    if fly_data_nord:
        DB.master.set_to_json('bridge:flyspray_rss_nord', fly_data_nord)
        DB.master.set_ttl('bridge:flyspray_rss_nord', ttl=1 * 3600)
    if fly_data_est:
        DB.master.set_to_json('bridge:flyspray_rss_est', fly_data_est)
        DB.master.set_ttl('bridge:flyspray_rss_est', ttl=1 * 3600)


@catch_log_except()
def dweet_job():
    DW_GET_URL = 'https://dweet.io/get/latest/dweet/for/'

    # https request
    r = requests.get(DW_GET_URL + dweet_id, timeout=10.0)
    # check error
    if r.status_code == 200:
        # parse data
        data_d = r.json()
        # update redis
        try:
            json_flyspray_est = dweet_decode(data_d['with'][0]['content']['raw_flyspray_est']).decode('utf8')
            DB.master.set_to_json("dweet:flyspray_rss_est", json.loads(json_flyspray_est))
            DB.master.set_ttl("dweet:flyspray_rss_est", ttl=3600)
        except IndexError as e:
            logging.error(f'except {type(e)} in  dweet_job(): {e}')
        try:
            json_flyspray_nord = dweet_decode(data_d['with'][0]['content']['raw_flyspray_nord']).decode('utf8')
            DB.master.set_to_json("dweet:flyspray_rss_nord", json.loads(json_flyspray_nord))
            DB.master.set_ttl("dweet:flyspray_rss_nord", ttl=3600)
        except IndexError as e:
            logging.error(f'except {type(e)} in  dweet_job(): {e}')


@catch_log_except()
def gsheet_job():
    # https request
    response = requests.get(gsheet_url, timeout=5.0)
    # process response
    d = dict()
    for line in response.iter_lines(decode_unicode=True):
        tag, value = line.split(',')
        d[tag] = value
    redis_d = dict(update=datetime.now().isoformat('T'), tags=d)
    DB.master.set_to_json('gsheet:grt', redis_d)
    DB.master.set_ttl('gsheet:grt', ttl=2 * 3600)


@catch_log_except()
def img_gmap_traffic_job():
    # http request
    r = requests.get(gmap_img_url, stream=True, timeout=5.0)
    if r.status_code == 200:
        # convert RAW img format (bytes) to Pillow image
        pil_img = PIL.Image.open(io.BytesIO(r.raw.read()))
        # crop image
        pil_img = pil_img.crop((0, 0, 560, 328))
        # pil_img.thumbnail([632, 328])
        img_io = io.BytesIO()
        pil_img.save(img_io, format='PNG')
        # store RAW PNG to redis key
        DB.master.set_bytes('img:traffic-map:png', img_io.getvalue())
        DB.master.set_ttl('img:traffic-map:png', 2 * 3600)


@catch_log_except()
def img_grt_tw_cloud_job():
    def is_camelcase(s):
        return s != s.lower() and '_' not in s

    # params
    tw_query = 'grtgaz exclude:retweets exclude:replies'
    tw_count = 100
    tw_oauth = OAuth1(tw_api_key, tw_api_secret, tw_access_token, tw_access_token_secret)
    # build url
    url = 'https://api.twitter.com/1.1/search/tweets.json?'
    url += 'q=%s&count=%i&result_type=recent&tweet_mode=extended'
    url %= (urllib.parse.quote(tw_query), tw_count)
    # do request
    r = requests.get(url, auth=tw_oauth, timeout=5.0)
    # check error
    if r.status_code == 200:
        d_tweets = r.json()
        d_hash_camel = {}
        c_hash = Counter()
        for tw in d_tweets['statuses']:
            tw_msg = tw['full_text']
            # search hashtag and count it
            for hashtag in re.findall(r'#(\w+)', tw_msg):
                h_key = hashtag.lower()
                if is_camelcase(hashtag):
                    d_hash_camel[h_key] = hashtag
                elif h_key not in d_hash_camel:
                    d_hash_camel[h_key] = h_key
                c_hash.update([h_key])

        # build WordCloud
        if c_hash:
            # build frequencies dict for generate step
            d_freq = {}
            for h_key, score in c_hash.most_common(25):
                d_freq[d_hash_camel[h_key]] = score
            # generate a word cloud image
            word_cloud = WordCloud(margin=5, width=327, height=226)
            word_cloud.generate_from_frequencies(frequencies=d_freq)
            img_io = io.BytesIO()
            pil_img = word_cloud.to_image()
            pil_img.save(img_io, format='PNG')
            # store RAW PNG to redis key
            DB.master.set_bytes('img:grt-tweet-wordcloud:png', img_io.getvalue())
            DB.master.set_ttl('img:grt-tweet-wordcloud:png', 2 * 3600)


@catch_log_except()
def local_info_job():
    # do request
    l_titles = []
    for post in feedparser.parse('https://france3-regions.francetvinfo.fr/societe/rss?r=hauts-de-france').entries:
        l_titles.append(post.title)
    DB.master.set_to_json('news:local', l_titles)
    DB.master.set_ttl('news:local', ttl=2 * 3600)


@catch_log_except()
def openweathermap_forecast_job():
    # build url
    ow_url = 'http://api.openweathermap.org/data/2.5/forecast?'
    ow_url += 'q=Loos,fr&appid=%s&units=metric&lang=fr' % ow_app_id
    # do request
    ow_d = requests.get(ow_url, timeout=5.0).json()
    # decode json
    t_today = None
    d_days = {}
    for i in range(0, 5):
        d_days[i] = dict(t_min=50.0, t_max=-50.0, main='', description='', icon='')
    # parse json
    for item in ow_d['list']:
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
    DB.master.set_to_json('weather:forecast:loos', d_days)
    DB.master.set_ttl('weather:forecast:loos', ttl=2 * 3600)


@catch_log_except()
def twitter_job():
    def tcl_normalize_str(tweet_str):
        tcl_str = ''
        for c in tweet_str:
            if ord(c) < 0xffff:
                tcl_str += c
        return html.unescape(tcl_str)

    # params
    tw_username = 'grtgaz'
    tw_count = 5
    tw_oauth = OAuth1(tw_api_key, tw_api_secret, tw_access_token, tw_access_token_secret)
    # build url
    url = 'https://api.twitter.com/1.1/statuses/user_timeline.json?'
    url += 'screen_name=%s&count=%i&tweet_mode=extended&exclude_retweets=true'
    url %= (tw_username, tw_count)
    # do request
    r = requests.get(url, auth=tw_oauth, timeout=5.0)
    # check error
    if r.status_code == 200:
        d_tweets = r.json()
        tweets_l = []
        # format all tweet and re-tweet
        for tw in d_tweets:
            # re-tweet
            if tw.get('retweeted_status', None):
                rt_user = tw['retweeted_status']['user']['screen_name']
                tweets_l.append(tcl_normalize_str('RT @%s: %s' % (rt_user, tw['retweeted_status']['full_text'])))
            # tweet
            else:
                tweets_l.append(tcl_normalize_str(tw['full_text']))
        # update redis
        d_redis = dict(tweets=tweets_l, update=datetime.now().isoformat('T'))
        DB.master.set_to_json('twitter:tweets:grtgaz', d_redis)
        DB.master.set_ttl('twitter:tweets:grtgaz', ttl=3600)


@catch_log_except()
def vigilance_job():
    # request XML data from server
    r = requests.get('http://vigilance.meteofrance.com/data/NXFR34_LFPW_.xml', timeout=10.0)
    # check error
    if r.status_code == 200:
        # dom parsing (convert UTF-8 r.text to XML char)
        dom = minidom.parseString(r.text.encode('ascii', 'xmlcharrefreplace'))
        # set dict for dep data
        vig_data = {'update': '', 'department': {}}
        # map build date
        tz = pytz.timezone('Europe/Paris')
        map_date = str(dom.getElementsByTagName('entetevigilance')[0].getAttribute('dateinsert'))
        map_dt = tz.localize(datetime(int(map_date[0:4]), int(map_date[4:6]),
                                      int(map_date[6:8]), int(map_date[8:10]),
                                      int(map_date[10:12])))
        vig_data['update'] = map_dt.isoformat()
        # parse every departments
        for items in dom.getElementsByTagName('datavigilance'):
            # current department
            dep_code = str(items.attributes['dep'].value)
            # get risk ID  if exist
            risk_id = []
            for risk in items.getElementsByTagName('risque'):
                risk_id.append(int(risk.attributes['valeur'].value))
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
        DB.master.set_to_json('weather:vigilance', vig_data)
        DB.master.set_ttl('weather:vigilance', ttl=2 * 3600)


@catch_log_except()
def weather_today_job():
    # request data from NOAA server (METAR of Lille-Lesquin Airport)
    r = requests.get('http://tgftp.nws.noaa.gov/data/observations/metar/stations/LFQQ.TXT',
                     timeout=10.0, headers={'User-Agent': USER_AGENT})
    # check error
    if r.status_code == 200:
        # extract METAR message
        metar_msg = r.content.decode().split('\n')[1]
        # METAR parse
        obs = Metar(metar_msg)
        # init and populate d_today dict
        d_today = {}
        # message date and time
        if obs.time:
            d_today['update_iso'] = obs.time.strftime('%Y-%m-%dT%H:%M:%SZ')
            d_today['update_fr'] = dt_utc_to_local(obs.time).strftime('%H:%M %d/%m')
        # current temperature
        if obs.temp:
            d_today['temp'] = round(obs.temp.value('C'))
        # current dew point
        if obs.dewpt:
            d_today['dewpt'] = round(obs.dewpt.value('C'))
        # current pressure
        if obs.press:
            d_today['press'] = round(obs.press.value('hpa'))
        # current wind speed
        if obs.wind_speed:
            d_today['w_speed'] = round(obs.wind_speed.value('KMH'))
        # current wind gust
        if obs.wind_gust:
            d_today['w_gust'] = round(obs.wind_gust.value('KMH'))
        # current wind direction
        if obs.wind_dir:
            # replace 'W'est by 'O'uest
            d_today['w_dir'] = obs.wind_dir.compass().replace('W', 'O')
        # weather status str
        d_today['descr'] = 'n/a'
        # store to redis
        DB.master.set_to_json('weather:today:loos', d_today)
        DB.master.set_ttl('weather:today:loos', ttl=2 * 3600)


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.info('board-import-app started')

    # init scheduler
    schedule.every(60).minutes.do(air_quality_atmo_hdf_job)
    schedule.every(2).minutes.do(bridge_job)
    schedule.every(15).minutes.do(dweet_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(2).minutes.do(img_gmap_traffic_job)
    schedule.every(30).minutes.do(img_grt_tw_cloud_job)
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(15).minutes.do(openweathermap_forecast_job)
    schedule.every(5).minutes.do(twitter_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(5).minutes.do(weather_today_job)
    # first call
    air_quality_atmo_hdf_job()
    bridge_job()
    dweet_job()
    gsheet_job()
    img_gmap_traffic_job()
    img_grt_tw_cloud_job()
    local_info_job()
    openweathermap_forecast_job()
    twitter_job()
    vigilance_job()
    weather_today_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)
