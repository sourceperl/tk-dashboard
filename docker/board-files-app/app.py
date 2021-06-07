#!/usr/bin/env python3

from configparser import ConfigParser
import functools
import glob
import hashlib
import json
import logging
import os
from os.path import basename, splitext, isfile, getsize, join
import pathlib
import time
import shutil
import subprocess
from xml.dom import minidom
import urllib3
from urllib.parse import urljoin, urlparse, quote, unquote
import dateutil.parser
import schedule
import redis
import requests

# configure package (disable warning for self-signed certificate)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# some const
HASH_BUF_SIZE = 64 * 1024
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_NO_CONTENT = 204
HTTP_MULTI_STATUS = 207
HTTP_UNAUTHORIZED = 401
# define files paths
DOWNLOAD_DOC_PDF_PATH = '/srv/dashboard/webdav/Affichage réglementaire'
DOWNLOAD_CAROUSEL_PNG_PATH = '/srv/dashboard/webdav/Carousel upload'
HMI_CAROUSEL_PNG_PATH = '/srv/dashboard/hmi/carousel_png'
HMI_DOC_PDF_PATH = '/srv/dashboard/hmi/doc_pdf'

# read config from board-conf-vol
cnf = ConfigParser()
cnf.read('/data/board-conf-vol/dashboard.conf')
carousel_max_png = int(cnf.get("carousel", "max_png", fallback=4))
# webdav
webdav_url = cnf.get("owncloud_dashboard", "webdav_url")
webdav_user = cnf.get("owncloud_dashboard", "webdav_user")
webdav_pass = cnf.get("owncloud_dashboard", "webdav_pass")
webdav_reglement_doc_dir = cnf.get("owncloud_dashboard", "webdav_reglement_doc_dir")
webdav_carousel_img_dir = cnf.get("owncloud_dashboard", "webdav_carousel_img_dir")


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


def ls_files(path, ext=""):
    return [join(path, file) for file in os.listdir(path) if isfile(join(path, file)) and file.endswith(ext)]


# some class
class WebDAVError(Exception):
    pass


class WebDAV:
    def __init__(self, url, username='', password='', timeout=5.0):
        # public
        self.last_http_code = 0
        self.timeout = timeout
        # private
        self._url = url
        self._url_path = urlparse(self._url).path
        self._session = requests.Session()
        # auth
        if username:
            self._session.auth = (username, password)

    def _url_with_path(self, path=''):
        return urljoin(self._url, quote(path))

    def upload(self, file_path, content=b''):
        # do request
        r = self._session.request(method='PUT', url=self._url_with_path(file_path),
                                  data=content, timeout=self.timeout, verify=False)
        self.last_http_code = r.status_code
        # return status (True if upload ok)
        # HTTP_CREATED => create file, HTTP_NO_CONTENT => update an existing file
        if not (r.status_code == HTTP_CREATED or r.status_code == HTTP_NO_CONTENT):
            raise WebDAVError('Error during upload of file "%s" (HTTP code is %i)' % (file_path,
                                                                                      self.last_http_code))

    def download(self, file_path):
        # do request
        r = self._session.request(method='GET', url=self._url_with_path(file_path),
                                  timeout=self.timeout, verify=False)
        self.last_http_code = r.status_code
        # return file content if request ok, None if error
        if r.status_code == HTTP_OK:
            return r.content
        else:
            raise WebDAVError('Error during download of file "%s" (HTTP code is %i)' % (file_path,
                                                                                        self.last_http_code))

    def delete(self, file_path):
        # do request
        r = self._session.request(method='DELETE', url=self._url_with_path(file_path),
                                  timeout=self.timeout, verify=False)
        self.last_http_code = r.status_code
        # return status (True if file delete is ok)
        if r.status_code != HTTP_NO_CONTENT:
            raise WebDAVError('Error during deletion of file "%s" (HTTP code is %i)' % (file_path,
                                                                                        self.last_http_code))

    def mkdir(self, dir_path):
        # do request
        r = self._session.request(method='MKCOL', url=self._url_with_path(dir_path),
                                  timeout=self.timeout, verify=False)
        self.last_http_code = r.status_code
        # return status (True if directory is created)
        if r.status_code != HTTP_CREATED:
            raise WebDAVError('Error during creation of dir "%s" (HTTP code is %i)' % (dir_path,
                                                                                       self.last_http_code))

    def ls(self, path='', depth=1):
        # build xml message
        propfind_request = '<?xml version="1.0" encoding="utf-8" ?>' \
                           '<d:propfind xmlns:d="DAV:">' \
                           '<d:prop><d:getlastmodified/><d:getcontentlength/></d:prop> ' \
                           '</d:propfind>'
        # do request
        r = self._session.request(method='PROPFIND',
                                  url=self._url_with_path(path),
                                  data=propfind_request, headers={'Depth': '%i' % depth},
                                  timeout=self.timeout, verify=False)
        self.last_http_code = r.status_code
        # check result
        if self.last_http_code == HTTP_MULTI_STATUS:
            # return a list of dict
            results_l = []
            # parse XML
            dom = minidom.parseString(r.text.encode('ascii', 'xmlcharrefreplace'))
            # for every d:response
            for response in dom.getElementsByTagName('d:response'):
                # in d:response/d:propstat/d:prop
                prop_stat = response.getElementsByTagName('d:propstat')[0]
                prop = prop_stat.getElementsByTagName('d:prop')[0]
                # d:getlastmodified
                get_last_modified = prop.getElementsByTagName('d:getlastmodified')[0].firstChild.data
                dt_last_modified = dateutil.parser.parse(get_last_modified)
                # d:getcontentlength
                try:
                    content_length = int(prop.getElementsByTagName('d:getcontentlength')[0].firstChild.data)
                except IndexError:
                    content_length = 0
                # href at d:response level
                href = response.getElementsByTagName('d:href')[0].firstChild.data
                # convert href to file path
                if href.startswith(self._url):
                    href = href[len(self._url):]
                elif href.startswith(self._url_path):
                    href = href[len(self._url_path):]
                file_path = unquote(href)
                file_path = file_path[len(path):]
                # feed result list
                results_l.append(dict(file_path=file_path, content_length=content_length,
                                      dt_last_modified=dt_last_modified))
            return results_l
        else:
            raise WebDAVError("Error during PROPFIND (ls) request (HTTP code is %i)" % self.last_http_code)


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
    master = CustomRedis(host='board-redis-srv', socket_timeout=4, socket_keepalive=True)


# sync owncloud carousel directory with local
@catch_log_except()
def owncloud_sync_carousel_job():
    # log sync start
    logging.debug('start of sync for owncloud carousel')

    # list local files
    local_files_l = [f for f in os.listdir(DOWNLOAD_CAROUSEL_PNG_PATH) if isfile(join(DOWNLOAD_CAROUSEL_PNG_PATH, f))]

    # list owncloud files (disallow directory)
    ownc_files_d = {}
    ownc_change = False
    for f_d in wdv.ls(webdav_carousel_img_dir):
        if f_d['file_path'] and not f_d['file_path'].endswith('/'):
            ownc_files_d[f_d['file_path']] = f_d['content_length']

    # exist only on local
    for f in list(set(local_files_l) - set(ownc_files_d)):
        logging.debug('"%s" exist only on local -> remove it' % f)
        os.remove(join(DOWNLOAD_CAROUSEL_PNG_PATH, f))
        ownc_change = True
    # exist only on remote
    for f in list(set(ownc_files_d) - set(local_files_l)):
        logging.debug('"%s" exist only on remote -> download it' % f)
        data = wdv.download(join(webdav_carousel_img_dir, f))
        if data:
            open(join(DOWNLOAD_CAROUSEL_PNG_PATH, f), 'wb').write(data)
        ownc_change = True
    # exist at both side (update only if file size change)
    for f in list(set(local_files_l).intersection(ownc_files_d)):
        local_size = int(getsize(join(DOWNLOAD_CAROUSEL_PNG_PATH, f)))
        remote_size = ownc_files_d[f]
        logging.debug('check "%s" remote size [%i]/local size [%i]' % (f, remote_size, local_size))
        if local_size != remote_size:
            logging.debug('"%s" size mismatch -> download it' % f)
            data = wdv.download(join(webdav_carousel_img_dir, f))
            if data:
                open(join(DOWNLOAD_CAROUSEL_PNG_PATH, f), 'wb').write(data)
            ownc_change = True

    # log sync end
    logging.debug('end of sync for owncloud carousel')

    # if change flag set, format carousel files (PDF, PNG, JPG) to match dashboard requirements
    if ownc_change:
        # log sync start
        logging.debug('start of carousel job')
        # extract md5 hash from name of png files in img directory
        file_hash_l = []
        for img_fname in os.listdir(HMI_CAROUSEL_PNG_PATH):
            if img_fname.endswith('.png'):
                # extract hash from index_md5.png or md5.png form
                try:
                    md5_hash = splitext(img_fname)[0].split('_')[1]
                except Exception:
                    md5_hash = splitext(img_fname)[0]
                file_hash_l.append(md5_hash)
        rm_hash_l = file_hash_l.copy()

        # get all files with pdf, png or jpg type in upload directory (images source), build a sorted list
        file_img_src_l = []
        for src_fname in os.listdir(DOWNLOAD_CAROUSEL_PNG_PATH):
            if isfile(join(DOWNLOAD_CAROUSEL_PNG_PATH, src_fname)):
                if src_fname.endswith(".pdf") or src_fname.endswith(".png") or src_fname.endswith(".jpg"):
                    file_img_src_l.append(src_fname)
        # build sorted list
        file_img_src_l.sort()
        # check if md5 of src file match img hash (in filename)
        for index, src_fname in enumerate(file_img_src_l):
            src_fname_full_path = join(DOWNLOAD_CAROUSEL_PNG_PATH, src_fname)
            # compute md5 hash of file
            md5 = hashlib.md5()
            with open(src_fname_full_path, 'rb') as fh:
                while True:
                    data = fh.read(HASH_BUF_SIZE)
                    if not data:
                        break
                    md5.update(data)
            md5_hash = md5.hexdigest()
            # build target img file name
            target_img_fname = "%03i_%s.png" % (index, md5_hash)
            # if file not already converted (md5 not in list): do mogrify
            if md5_hash not in file_hash_l:
                logging.debug("hash %s not exist, build it" % md5_hash)
                # convert to PNG
                subprocess.call("mogrify -density 500 -resize 655x453 -format png".split() +
                                [src_fname_full_path + "[0]"])
                # move png file from upload dir to img dir with sort index as first 3 chars
                shutil.move(splitext(src_fname_full_path)[0] + ".png",
                            join(HMI_CAROUSEL_PNG_PATH, target_img_fname))
            # if src file is already converted, just check index
            else:
                # reindex: check current index, update it if need
                for img_fname_to_check in glob.glob(join(HMI_CAROUSEL_PNG_PATH, "*%s.png" % md5_hash)):
                    if not img_fname_to_check.endswith(target_img_fname):
                        logging.debug("rename %s to %s" % (basename(img_fname_to_check), target_img_fname))
                        os.rename(img_fname_to_check, join(HMI_CAROUSEL_PNG_PATH, target_img_fname))
                # remove current hash from rm list
                try:
                    rm_hash_l.remove(md5_hash)
                except ValueError:
                    pass

        # remove orphan img file (without src)
        for rm_hash in rm_hash_l:
            for img_fname_to_rm in glob.glob(join(HMI_CAROUSEL_PNG_PATH, "*%s.png" % rm_hash)):
                logging.debug("remove old file %s" % img_fname_to_rm)
                os.remove(img_fname_to_rm)

        # log sync end
        logging.debug("end of carousel job")


# sync owncloud document directory with local
@catch_log_except()
def owncloud_sync_doc_job():
    # log sync start
    logging.debug('start of sync for owncloud doc')

    # list local files
    local_files_l = [f for f in os.listdir(DOWNLOAD_DOC_PDF_PATH) if isfile(join(DOWNLOAD_DOC_PDF_PATH, f))]

    # list owncloud files (disallow directory)
    ownc_files_d = {}
    for f_d in wdv.ls(webdav_reglement_doc_dir):
        if f_d['file_path'] and not f_d['file_path'].endswith('/'):
            ownc_files_d[f_d['file_path']] = f_d['content_length']

    # exist only on local
    for f in list(set(local_files_l) - set(ownc_files_d)):
        logging.debug('"%s" exist only on local -> remove it' % f)
        os.remove(join(DOWNLOAD_DOC_PDF_PATH, f))
    # exist only on remote
    for f in list(set(ownc_files_d) - set(local_files_l)):
        logging.debug('"%s" exist only on remote -> download it' % f)
        data = wdv.download(join(webdav_reglement_doc_dir, f))
        if data:
            open(join(DOWNLOAD_DOC_PDF_PATH, f), 'wb').write(data)
    # exist at both side (update only if file size change)
    for f in list(set(local_files_l).intersection(ownc_files_d)):
        local_size = int(getsize(join(DOWNLOAD_DOC_PDF_PATH, f)))
        remote_size = ownc_files_d[f]
        logging.debug('check "%s" remote size [%i]/local size [%i]' % (f, remote_size, local_size))
        if local_size != remote_size:
            logging.debug('"%s" size mismatch -> download it' % f)
            data = wdv.download(join(webdav_reglement_doc_dir, f))
            if data:
                open(join(DOWNLOAD_DOC_PDF_PATH, f), 'wb').write(data)
    # log sync end
    logging.debug('end of sync for owncloud doc')


# check if the owncloud directories has been updated by users (start sync jobs if need)
@catch_log_except()
def check_owncloud_update_job():
    for f in wdv.ls():
        name = f['file_path']
        update_ts = int(f['dt_last_modified'].timestamp())
        # document update ?
        if name == webdav_reglement_doc_dir:
            try:
                last_update = int(DB.master.get('owncloud:document:update_ts'))
            except TypeError:
                last_update = 0
            # update need
            if update_ts > last_update:
                owncloud_sync_doc_job()
                DB.master.set('owncloud:document:update_ts', update_ts)
        # carousel update ?
        elif name == webdav_carousel_img_dir:
            try:
                last_update = int(DB.master.get('owncloud:carousel:update_ts'))
            except TypeError:
                last_update = 0
            # update need
            if update_ts > last_update:
                owncloud_sync_carousel_job()
                DB.master.set('owncloud:carousel:update_ts', update_ts)


# main
if __name__ == '__main__':
    # logging setup
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)
    logging.info('board-files-app started')

    # create directory in data volume if need
    pathlib.Path(DOWNLOAD_DOC_PDF_PATH).mkdir(parents=True, exist_ok=True)
    pathlib.Path(DOWNLOAD_CAROUSEL_PNG_PATH).mkdir(parents=True, exist_ok=True)
    pathlib.Path(HMI_CAROUSEL_PNG_PATH).mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(DOWNLOAD_DOC_PDF_PATH, HMI_DOC_PDF_PATH)
    except FileExistsError:
        pass

    # init webdav client
    wdv = WebDAV(webdav_url, username=webdav_user, password=webdav_pass)

    # init scheduler
    schedule.every(5).minutes.do(check_owncloud_update_job)
    schedule.every(4).hours.do(owncloud_sync_carousel_job)
    schedule.every(4).hours.do(owncloud_sync_doc_job)
    # first call
    check_owncloud_update_job()

    # main loop
    while True:
        # schedule jobs
        schedule.run_pending()
        # wait next loop
        time.sleep(1)
