#!/usr/bin/env python3

import base64
from configparser import ConfigParser
from datetime import datetime
import math
import secrets
import urllib.parse
import hashlib
import json
import logging
import functools
import io
import time
from xml.dom import minidom
import zlib
import feedparser
import os
import redis
import requests
import schedule
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
from metar.Metar import Metar
import pytz
import pdf2image
import PIL.Image
import PIL.ImageDraw
from webdav import WebDAV

# some const
USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:2.0.1) Gecko/20100101 Firefox/4.0.1'

# some var
owc_doc_dir_last_sync = 0
owc_car_dir_last_sync = 0

# read config
cnf = ConfigParser()
cnf.read('/data/conf/board.conf')
# redis
redis_user = cnf.get('redis', 'user')
redis_pass = cnf.get('redis', 'pass')
# gmap img traffic
gmap_img_url = cnf.get('gmap_img', 'img_url')
# gsheet
gsheet_url = cnf.get('gsheet', 'url')
# openweathermap
ow_app_id = cnf.get('openweathermap', 'app_id')
# dweet
dweet_id = cnf.get('dweet', 'id')
dweet_key = cnf.get('dweet', 'key')
# webdav
webdav_url = cnf.get('owncloud_dashboard', 'webdav_url')
webdav_user = cnf.get('owncloud_dashboard', 'webdav_user')
webdav_pass = cnf.get('owncloud_dashboard', 'webdav_pass')
webdav_reglement_doc_dir = cnf.get('owncloud_dashboard', 'webdav_reglement_doc_dir')
webdav_carousel_img_dir = cnf.get('owncloud_dashboard', 'webdav_carousel_img_dir')


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
    def set_bytes(self, name, value, ttl=None):
        return self.set(name, value, ex=ttl)

    @catch_log_except(catch=redis.RedisError)
    def get_bytes(self, name):
        return self.get(name)

    @catch_log_except(catch=redis.RedisError)
    def set_str(self, name, value, ttl=None):
        return self.set(name, value, ex=ttl)

    @catch_log_except(catch=(redis.RedisError, AttributeError))
    def get_str(self, name):
        return self.get(name).decode('utf-8')

    @catch_log_except(catch=(redis.RedisError, AttributeError, json.decoder.JSONDecodeError))
    def set_to_json(self, name, obj, ttl=None):
        return self.set(name, json.dumps(obj), ex=ttl)

    @catch_log_except(catch=(redis.RedisError, AttributeError, json.decoder.JSONDecodeError))
    def get_from_json(self, name):
        return json.loads(self.get(name).decode('utf-8'))


class DB:
    # create connector
    main = CustomRedis(host='board-redis-srv', username=redis_user, password=redis_pass,
                       socket_timeout=4, socket_keepalive=True)


# some function
@catch_log_except()
def air_quality_atmo_ge_job():
    url = 'https://services3.arcgis.com/' + \
          'Is0UwT37raQYl9Jj/arcgis/rest/services/ind_grandest_5j/FeatureServer/0/query' + \
          '?where=%s' % urllib.parse.quote('code_zone IN (54395, 57463, 51454, 67482)') + \
          '&outFields=date_ech, code_qual, lib_qual, lib_zone, code_zone' + \
          '&returnGeometry=false&resultRecordCount=48' + \
          '&orderByFields=%s&f=json' % urllib.parse.quote('date_ech ASC')
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
        d_air_quality = {'nancy': zones_d.get(54395, 0),
                         'metz': zones_d.get(57463, 0),
                         'reims': zones_d.get(51454, 0),
                         'strasbourg': zones_d.get(67482, 0)}
        # update redis
        DB.main.set_to_json('json:atmo', d_air_quality, ttl=6 * 3600)


@catch_log_except()
def dir_est_img_job():
    # retrieve DIR-est webcams: Houdemont, Velaine-en-Haye, Saint-Nicolas, Côte de Flavigny
    for id_redis, lbl_cam, get_code in [('houdemont', 'Houdemont', '18'), ('velaine', 'Velaine', '53'),
                                        ('st-nicolas', 'Saint-Nicolas', '49'), ('flavigny', 'Flavigny', '5')]:
        r = requests.get('https://webcam.dir-est.fr/app.php/lastimg/%s' % get_code)
        if r.status_code == 200:
            # load image to PIL and resize it
            img = PIL.Image.open(io.BytesIO(r.content))
            img.thumbnail([224, 235])
            # add text to image
            txt_img = '%s - %s' % (lbl_cam, datetime.now().strftime('%H:%M'))
            font = PIL.ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMono.ttf', 16)
            draw = PIL.ImageDraw.Draw(img)
            draw.text((5, 5), txt_img, (0x10, 0x0e, 0x0e), font=font)
            # save image as PNG for redis
            redis_io = io.BytesIO()
            img.save(redis_io, format='PNG')
            # update redis
            DB.main.set_bytes('img:dir-est:%s:png' % id_redis, redis_io.getvalue(), ttl=3600)


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
            DB.main.set_to_json('json:dweet:fly-est', json.loads(json_flyspray_est), ttl=3600)
        except IndexError as e:
            logging.error(f'except {type(e)} in  dweet_job(): {e}')
        try:
            json_flyspray_nord = dweet_decode(data_d['with'][0]['content']['raw_flyspray_nord']).decode('utf8')
            DB.main.set_to_json('json:dweet:fly-nord', json.loads(json_flyspray_nord), ttl=3600)
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
    DB.main.set_to_json('json:gsheet', redis_d, ttl=2 * 3600)


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
        DB.main.set_bytes('img:traffic-map:png', img_io.getvalue(), 2 * 3600)


@catch_log_except()
def local_info_job():
    # do request
    l_titles = []
    for post in feedparser.parse('https://france3-regions.francetvinfo.fr/societe/rss?r=grand-est').entries:
        l_titles.append(post.title)
    DB.main.set_to_json('json:news', l_titles, ttl=2 * 3600)


@catch_log_except()
def owc_updated_job():
    # check if the owncloud directories has been updated by users (start sync jobs if need)
    global owc_doc_dir_last_sync, owc_car_dir_last_sync

    for f in wdv.ls():
        item = f['file_path']
        item_last_modified = int(f['dt_last_modified'].timestamp())
        # document update ?
        if item == webdav_reglement_doc_dir:
            # update need
            if item_last_modified > owc_doc_dir_last_sync:
                logging.debug(f'"{webdav_reglement_doc_dir}" seem updated: run "owncloud_sync_doc_job"')
                owc_sync_doc_job()
                owc_doc_dir_last_sync = item_last_modified
        # carousel update ?
        elif item == webdav_carousel_img_dir:
            # update need
            if item_last_modified > owc_car_dir_last_sync:
                logging.debug(f'"{webdav_carousel_img_dir}" seem updated: run "owncloud_sync_carousel_job"')
                owc_sync_carousel_job()
                owc_car_dir_last_sync = item_last_modified


@catch_log_except()
def owc_sync_carousel_job():
    # sync owncloud carousel directory with local
    # local constants
    DIR_CAR_INFOS = 'dir:carousel:infos'
    DIR_CAR_RAW = 'dir:carousel:raw:min-png'

    # local functions
    def update_carousel_raw_data(filename, raw_data):
        # build json infos record
        md5 = hashlib.md5(raw_data).hexdigest()
        js_infos = json.dumps(dict(size=len(raw_data), md5=md5))
        # convert raw data to PNG thumbnails
        # create default error image
        img_to_redis = PIL.Image.new("RGB", (655, 453), (255, 255, 255))
        draw = PIL.ImageDraw.Draw(img_to_redis)
        draw.text((0, 0), f'loading error (src: "{filename}")', (0, 0, 0))
        # replace default image by convert result
        try:
            # convert png and jpg file
            if filename.lower().endswith('.png') or filename.lower().endswith('.jpg'):
                # image to PIL
                img_to_redis = PIL.Image.open(io.BytesIO(raw_data))
            # convert pdf file
            elif filename.lower().endswith('.pdf'):
                # PDF to PIL: convert first page to PIL image
                img_to_redis = pdf2image.convert_from_bytes(raw_data)[0]
        except Exception:
            pass
        # resize and format as raw png
        img_to_redis.thumbnail([655, 453])
        io_to_redis = io.BytesIO()
        img_to_redis.save(io_to_redis, format='PNG')
        # redis add  (atomic write)
        pipe = DB.main.pipeline()
        pipe.hset(DIR_CAR_INFOS, filename, js_infos)
        pipe.hset(DIR_CAR_RAW, filename, io_to_redis.getvalue())
        pipe.execute()

    # log sync start
    logging.info('start of sync for owncloud carousel')
    # list local redis files
    local_files_d = {}
    for f_name, js_infos in DB.main.hgetall(DIR_CAR_INFOS).items():
        try:
            filename = f_name.decode()
            size = json.loads(js_infos)['size']
            local_files_d[filename] = size
        except ValueError:
            pass
    # check "dir:carousel:raw:min-png" consistency
    raw_file_l = [f.decode() for f in DB.main.hkeys(DIR_CAR_RAW)]
    # remove orphan infos record
    for f in list(set(local_files_d) - set(raw_file_l)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_CAR_INFOS}"')
        DB.main.hdel(DIR_CAR_INFOS, f)
        del local_files_d[f]
    # remove orphan raw-png record
    for f in list(set(raw_file_l) - set(local_files_d)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_CAR_RAW}"')
        DB.main.hdel(DIR_CAR_RAW, f)
    # list owncloud files (disallow directory)
    own_files_d = {}
    for f_d in wdv.ls(webdav_carousel_img_dir):
        file_path = f_d['file_path']
        size = f_d['content_length']
        if file_path and not file_path.endswith('/'):
            # download filter: ignore txt file or heavy fie (>10 MB)
            ok_load = not file_path.lower().endswith('.txt') \
                      and (size < 10 * 1024 * 1024)
            if ok_load:
                own_files_d[f_d['file_path']] = size
    # exist only on local redis
    for f in list(set(local_files_d) - set(own_files_d)):
        logging.info(f'"{f}" exist only on local -> remove it')
        # redis remove (atomic)
        pipe = DB.main.pipeline()
        pipe.hdel(DIR_CAR_INFOS, f)
        pipe.hdel(DIR_CAR_RAW, f)
        pipe.execute()
    # exist only on remote owncloud
    for f in list(set(own_files_d) - set(local_files_d)):
        logging.info('"%s" exist only on remote -> download it' % f)
        data = wdv.download(os.path.join(webdav_carousel_img_dir, f))
        if data:
            update_carousel_raw_data(f, data)
    # exist at both side (update only if file size change)
    for f in list(set(local_files_d).intersection(own_files_d)):
        local_size = local_files_d[f]
        remote_size = own_files_d[f]
        logging.debug(f'check "{f}" remote size [{remote_size}]/local size [{local_size}]')
        if local_size != remote_size:
            logging.info(f'"{f}" size mismatch -> download it')
            data = wdv.download(os.path.join(webdav_carousel_img_dir, f))
            if data:
                update_carousel_raw_data(f, data)
    # log sync end
    logging.info('end of sync for owncloud carousel')


@catch_log_except()
def owc_sync_doc_job():
    # sync owncloud document directory with local
    # local constants
    DIR_DOC_INFOS = 'dir:doc:infos'
    DIR_DOC_RAW = 'dir:doc:raw'

    # local functions
    def update_doc_raw_data(filename, raw_data):
        # build json infos record
        md5 = hashlib.md5(raw_data).hexdigest()
        js_infos = json.dumps(dict(size=len(raw_data), md5=md5))
        # redis add  (atomic write)
        pipe = DB.main.pipeline()
        pipe.hset(DIR_DOC_INFOS, filename, js_infos)
        pipe.hset(DIR_DOC_RAW, filename, raw_data)
        pipe.execute()

    # log sync start
    logging.info('start of sync for owncloud doc')
    # list local redis files
    local_files_d = {}
    for f_name, js_infos in DB.main.hgetall(DIR_DOC_INFOS).items():
        try:
            filename = f_name.decode()
            size = json.loads(js_infos)['size']
            local_files_d[filename] = size
        except ValueError:
            pass
    # check "dir:doc:raw:min-png" consistency
    raw_file_l = [f.decode() for f in DB.main.hkeys(DIR_DOC_RAW)]
    # remove orphan infos record
    for f in list(set(local_files_d) - set(raw_file_l)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_DOC_INFOS}"')
        DB.main.hdel(DIR_DOC_INFOS, f)
        del local_files_d[f]
    # remove orphan raw-png record
    for f in list(set(raw_file_l) - set(local_files_d)):
        logging.debug(f'remove orphan "{f}" record in hash "{DIR_DOC_RAW}"')
        DB.main.hdel(DIR_DOC_RAW, f)
    # list owncloud files (disallow directory)
    own_files_d = {}
    for f_d in wdv.ls(webdav_reglement_doc_dir):
        file_path = f_d['file_path']
        size = f_d['content_length']
        if file_path and not file_path.endswith('/'):
            # download filter: ignore txt file or heavy fie (>10 MB)
            ok_load = not file_path.lower().endswith('.txt') \
                      and (size < 10 * 1024 * 1024)
            if ok_load:
                own_files_d[f_d['file_path']] = size
    # exist only on local redis
    for f in list(set(local_files_d) - set(own_files_d)):
        logging.info(f'"{f}" exist only on local -> remove it')
        # redis remove (atomic)
        pipe = DB.main.pipeline()
        pipe.hdel(DIR_DOC_INFOS, f)
        pipe.hdel(DIR_DOC_RAW, f)
        pipe.execute()
    # exist only on remote owncloud
    for f in list(set(own_files_d) - set(local_files_d)):
        logging.info(f'"{f}" exist only on remote -> download it')
        data = wdv.download(os.path.join(webdav_reglement_doc_dir, f))
        if data:
            update_doc_raw_data(f, data)
    # exist at both side (update only if file size change)
    for f in list(set(local_files_d).intersection(own_files_d)):
        local_size = local_files_d[f]
        remote_size = own_files_d[f]
        logging.debug(f'check "{f}" remote size [{remote_size}]/local size [{local_size}]')
        if local_size != remote_size:
            logging.info(f'"{f}" size mismatch -> download it')
            data = wdv.download(os.path.join(webdav_reglement_doc_dir, f))
            if data:
                update_doc_raw_data(f, data)
    # log sync end
    logging.info('end of sync for owncloud doc')


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
        DB.main.set_to_json('json:vigilance', vig_data, ttl=2 * 3600)


@catch_log_except()
def weather_today_job():
    # request data from NOAA server (METAR of Nancy-Essey Airport)
    r = requests.get('http://tgftp.nws.noaa.gov/data/observations/metar/stations/LFSN.TXT',
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
        DB.main.set_to_json('json:weather:today:nancy', d_today, ttl=2 * 3600)


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)
    logging.getLogger('PIL').setLevel(logging.INFO)
    logging.info('board-import-app started')

    # init webdav client
    wdv = WebDAV(webdav_url, username=webdav_user, password=webdav_pass)

    # init scheduler
    schedule.every(5).minutes.do(owc_updated_job)
    schedule.every(1).hours.do(owc_sync_carousel_job)
    schedule.every(1).hours.do(owc_sync_doc_job)
    schedule.every(60).minutes.do(air_quality_atmo_ge_job)
    schedule.every(5).minutes.do(dir_est_img_job)
    schedule.every(15).minutes.do(dweet_job)
    schedule.every(5).minutes.do(gsheet_job)
    schedule.every(2).minutes.do(img_gmap_traffic_job)
    schedule.every(5).minutes.do(local_info_job)
    schedule.every(5).minutes.do(vigilance_job)
    schedule.every(5).minutes.do(weather_today_job)
    # first call
    air_quality_atmo_ge_job()
    dir_est_img_job()
    dweet_job()
    gsheet_job()
    img_gmap_traffic_job()
    local_info_job()
    vigilance_job()
    weather_today_job()
    owc_updated_job()

    # main loop
    while True:
        schedule.run_pending()
        time.sleep(1)
