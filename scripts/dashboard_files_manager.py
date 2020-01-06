#!/usr/bin/env python3

from configparser import ConfigParser
import hashlib
import logging
import os
from os.path import splitext, isfile, getsize, join, expanduser
import time
import traceback
import shutil
import subprocess
from xml.dom import minidom
import urllib3
import urllib.parse
import dateutil.parser
import schedule
import redis
import requests
import webdav.client as wc

# configure package (disable warning for self-signed certificate)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# some const
HASH_BUF_SIZE = 64 * 1024
HTTP_MULTI_STATUS = 207

# read config
cnf = ConfigParser()
cnf.read(expanduser('~/.dashboard_config'))
dashboard_root_path = cnf.get("paths", "dashboard_root_path")
reglement_doc_path = dashboard_root_path + cnf.get("paths", "reglement_doc_dir")
carousel_img_path = dashboard_root_path + cnf.get("paths", "carousel_img_dir")
carousel_upload_dir = dashboard_root_path + cnf.get("paths", "carousel_upload_dir")
carousel_max_png = int(cnf.get("carousel", "max_png", fallback=4))
webdav_host = cnf.get("owncloud_dashboard", "webdav_host")
webdav_root = cnf.get("owncloud_dashboard", "webdav_root")
webdav_user = cnf.get("owncloud_dashboard", "webdav_user")
webdav_pass = cnf.get("owncloud_dashboard", "webdav_pass")
webdav_reglement_doc_dir = cnf.get("owncloud_dashboard", "webdav_reglement_doc_dir")
webdav_carousel_img_dir = cnf.get("owncloud_dashboard", "webdav_carousel_img_dir")


# some functions
def ls_files(path, ext=""):
    return [join(path, file) for file in os.listdir(path) if isfile(join(path, file)) and file.endswith(ext)]


def update_img_carousel_job():
    try:
        # log sync start
        logging.debug("start of carousel job")
        # extract md5 hash from name of png files in img directory
        files_hash_l = [splitext(f)[0] for f in os.listdir(carousel_img_path) if f.endswith(".png")]
        rm_hash_l = files_hash_l.copy()

        # for all files in display dir
        for f in ls_files(carousel_upload_dir):
            # filters supported file types
            if f.endswith(".pdf") or f.endswith(".png") or f.endswith(".jpg"):
                # compute md5 hash of file
                md5 = hashlib.md5()
                with open(f, 'rb') as fh:
                    while True:
                        data = fh.read(HASH_BUF_SIZE)
                        if not data:
                            break
                        md5.update(data)
                md5_hash = md5.hexdigest()
                # file not already converted (md5 exist ?)
                if md5_hash not in files_hash_l:
                    logging.debug("%s not exist, build it" % md5_hash)
                    # convert to PNG
                    subprocess.call("mogrify -density 500 -resize 655x453 -format png".split() + [f + "[0]"])
                    # move png file from upload dir to img dir
                    shutil.move(splitext(f)[0] + ".png", join(carousel_img_path, "%s.png" % md5_hash))
                else:
                    # remove current hash from rm list
                    try:
                        rm_hash_l.remove(md5_hash)
                    except ValueError:
                        pass

        # remove file from
        for f_hash in rm_hash_l:
            f_full_path = join(carousel_img_path, "%s.png" % f_hash)
            logging.debug("remove old file %s" % f_full_path)
            os.remove(f_full_path)

        # log sync end
        logging.debug("end of carousel job")
    except Exception:
        logging.error(traceback.format_exc())
        return None


def owncloud_sync_carousel_job():
    try:
        # log sync start
        logging.debug('start of sync for owncloud carousel')

        # list local files
        local_files_l = [f for f in os.listdir(carousel_upload_dir) if isfile(join(carousel_upload_dir, f))]

        # list owncloud files
        ownc_files_l = wdc.list(webdav_carousel_img_dir)
        ownc_files_l = [f for f in ownc_files_l if not f.endswith('/')]
        ownc_change = False

        # exist only on local
        for f in list(set(local_files_l) - set(ownc_files_l)):
            logging.debug('"%s" exist only on local -> remove it' % f)
            os.remove(join(carousel_upload_dir, f))
            ownc_change = True
        # exist only on remote
        for f in list(set(ownc_files_l) - set(local_files_l)):
            logging.debug('"%s" exist only on remote -> download it' % f)
            wdc.download(join(webdav_carousel_img_dir, f), local_path=join(carousel_upload_dir, f))
            ownc_change = True
        # exist at both side (update only if file size change)
        for f in list(set(local_files_l).intersection(ownc_files_l)):
            local_size = int(getsize(join(carousel_upload_dir, f)))
            remote_size = int(wdc.info(join(webdav_carousel_img_dir, f))['size'])
            logging.debug('check "%s" remote size [%i]/local size [%i]' % (f, remote_size, local_size))
            if local_size != remote_size:
                logging.debug('"%s" size mismatch -> download it' % f)
                wdc.download(join(webdav_carousel_img_dir, f), local_path=join(carousel_upload_dir, f))
                ownc_change = True

        # log sync end
        logging.debug('end of sync for owncloud carousel')

        # notify carousel manager
        if ownc_change:
            r.publish("dashboard:trigger", "carousel_update")
    except Exception:
        logging.error(traceback.format_exc())
        return None


def owncloud_sync_doc_job():
    try:
        # log sync start
        logging.debug('start of sync for owncloud doc')

        # list local files
        local_files_l = [f for f in os.listdir(reglement_doc_path) if isfile(join(reglement_doc_path, f))]

        # list owncloud files
        ownc_files_l = wdc.list(webdav_reglement_doc_dir)
        ownc_files_l = [f for f in ownc_files_l if not f.endswith('/')]

        # exist only on local
        for f in list(set(local_files_l) - set(ownc_files_l)):
            logging.debug('"%s" exist only on local -> remove it' % f)
            os.remove(join(reglement_doc_path, f))
        # exist only on remote
        for f in list(set(ownc_files_l) - set(local_files_l)):
            logging.debug('"%s" exist only on remote -> download it' % f)
            wdc.download(join(webdav_reglement_doc_dir, f), local_path=join(reglement_doc_path, f))
        # exist at both side (update only if file size change)
        for f in list(set(local_files_l).intersection(ownc_files_l)):
            local_size = int(getsize(join(reglement_doc_path, f)))
            remote_size = int(wdc.info(join(webdav_reglement_doc_dir, f))['size'])
            logging.debug('check "%s" remote size [%i]/local size [%i]' % (f, remote_size, local_size))
            if local_size != remote_size:
                logging.debug('"%s" size mismatch -> download it' % f)
                wdc.download(join(webdav_reglement_doc_dir, f), local_path=join(reglement_doc_path, f))
        # log sync end
        logging.debug('end of sync for owncloud doc')
    except Exception:
        logging.error(traceback.format_exc())
        return None


def check_owncloud_update_job():
    propfind_request = '<?xml version="1.0" encoding="utf-8" ?>' \
                       '<d:propfind xmlns:d="DAV:"><d:prop><d:getlastmodified/></d:prop></d:propfind>'
    try:
        # init request session
        s = requests.Session()
        s.auth = (webdav_user, webdav_pass)
        req = s.request(method='PROPFIND', url=webdav_host + webdav_root,
                        data=propfind_request, headers={'Depth': '1'}, verify=False)
        # check result
        if req.status_code == HTTP_MULTI_STATUS:
            # parse XML
            dom = minidom.parseString(req.text.encode('ascii', 'xmlcharrefreplace'))
            # for every d:response
            for response in dom.getElementsByTagName('d:response'):
                href = response.getElementsByTagName('d:href')[0].firstChild.data
                # d:getlastmodified, oc:checksum and oc:size in d:response/d:propstat/d:prop
                prop_stat = response.getElementsByTagName('d:propstat')[0]
                prop = prop_stat.getElementsByTagName('d:prop')[0]
                get_last_modified = prop.getElementsByTagName('d:getlastmodified')[0].firstChild.data
                dt_last_modified = dateutil.parser.parse(get_last_modified)
                name = urllib.parse.unquote(href[len(webdav_root):])[1:]
                update_ts = int(dt_last_modified.timestamp())
                # document update ?
                if name == webdav_reglement_doc_dir:
                    try:
                        last_update = int(r.get('owncloud:document:update_ts'))
                    except TypeError:
                        last_update = 0
                    # update need
                    if update_ts > last_update:
                        r.publish('dashboard:trigger', 'owc_document')
                        r.set('owncloud:document:update_ts', update_ts)
                # carousel update ?
                elif name == webdav_carousel_img_dir:
                    try:
                        last_update = int(r.get('owncloud:carousel:update_ts'))
                    except TypeError:
                        last_update = 0
                    # update need
                    if update_ts > last_update:
                        r.publish('dashboard:trigger', 'owc_carousel')
                        r.set('owncloud:carousel:update_ts', update_ts)
    except Exception:
        logging.error(traceback.format_exc())
        return None


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s')
    # logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)

    # init webdav client
    wdc = wc.Client(dict(webdav_hostname=webdav_host, webdav_root=webdav_root,
                         webdav_login=webdav_user, webdav_password=webdav_pass))
    wdc.default_options["SSL_VERIFYPEER"] = False
    wdc.default_options["SSL_VERIFYHOST"] = False
    wdc.default_options["TIMEOUT"] = 5

    # subscribe to redis publish channel
    r = redis.StrictRedis()
    ps = r.pubsub()
    ps.subscribe(["dashboard:trigger"])

    # init scheduler
    schedule.every(2).minutes.do(check_owncloud_update_job)
    schedule.every(4).hours.do(owncloud_sync_carousel_job)
    schedule.every(4).hours.do(owncloud_sync_doc_job)
    # first call
    check_owncloud_update_job()

    # main loop
    while True:
        # schedule jobs
        schedule.run_pending()
        # check notify on redis
        try:
            msg = ps.get_message()
            if msg and msg["type"] == "message":
                # immediate carousel update on redis notify
                if msg["data"].decode() == "carousel_update":
                    update_img_carousel_job()
                # immediate owncloud document update on redis notify
                if msg["data"].decode() == "owc_document":
                    owncloud_sync_doc_job()
                # immediate owncloud carousel update on redis notify
                if msg["data"].decode() == "owc_carousel":
                    owncloud_sync_carousel_job()
        except Exception:
            logging.error(traceback.format_exc())
        # wait next loop
        time.sleep(1)
