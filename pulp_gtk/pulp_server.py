#!/usr/bin/env python3

import json
import multiprocessing
import re
import os
import subprocess
import urllib.parse
import wsgiref.simple_server

class PulpRequestHandler(wsgiref.simple_server.WSGIRequestHandler):
    def log_message(self, fmt, *args):
        print("PulpServer: %s [%s] %s" %
              (self.client_address[0],
               self.log_date_time_string(),
               fmt%args))

class PulpServer:

    @classmethod
    def start_multiprocess(cls):
        queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target = cls.serve_forever,
            args = (queue,),
            daemon = True
        )
        proc.start()
        return proc, queue

    @classmethod
    def serve_forever(cls, queue):
        app = cls(queue)
        httpd = wsgiref.simple_server.make_server (
            'localhost', 23232, app,
            handler_class = PulpRequestHandler
        )
        httpd.serve_forever()

    def __init__(self, queue):
        self.queue = queue

    def __call__(self, environ, start_response):

        path = environ['PATH_INFO']
        query = environ['QUERY_STRING']

        response_body = ""

        if path == "/list":
            response_body = self.get_list()
        elif path == "/short_list":
            response_body = self.get_short_list()
        elif path == "/search":
            response_body = self.get_search(query)
        elif path == "/open":
            self.do_open(query)
        elif path == "/view":
            self.do_view(query)
        elif path == "/synctex_forward_search":
            self.do_synctex_forward_search(query)

        response_body = response_body.encode('utf-8')

        status = '200 OK'
        response_headers = [
            ('Content-Type', 'text/plain; charset=utf-8'),
            ('Content-Length', str(len(response_body)))
        ]
        start_response(status, response_headers)

        return [response_body]

    def get_list(self):
        return self.gen_file_list(lambda x:x)

    def get_short_list(self):
        def filter_fun(d):
            return (d['title_regex'], d['file_name_safe'])
        return self.gen_file_list(filter_fun, indent=None)

    def gen_file_list(self, filter_fun, indent=2):
        files = os.listdir("/Users/roi/Google Drive/Zotero")
        dics = []
        rgx = re.compile(r"""
                         (?P<file_name>
                             (?P<authors>.+)
                             _
                             (?P<year>\d\d\d\d)?
                             _
                             (?P<title>.*)
                             \.
                             (pdf|djvu|ps)
                         )
                         """, re.X)
        rgx2 = re.compile(r"[^a-zA-Z\d]+")
        for f in files:
            m = rgx.match(f)
            if m:
                d = m.groupdict()
                d['authors'] = d['authors'].split("_")
                d['title'] = d['title'].replace("_", " ")
                d['title_regex'] = rgx2.sub(".*", d['title'])
                d['file_name_safe'] = urllib.parse.quote_plus(d['file_name'])
                d = filter_fun(d)
                if d is not None:
                    dics.append(d)
        return json.dumps(dics, indent=indent)

    def get_search(self, query):
        files = os.listdir("/Users/roi/Google Drive/Zotero")
        query = urllib.parse.unquote_plus(query)
        q_rgx = re.sub(r"[^a-zA-Z\d]+", ".*", query)
        rgx = re.compile(r"""
                         (?P<file_name>
                             (?P<authors>.+)
                             _
                             (?P<year>\d\d\d\d)?
                             _
                             (?P<title>.*%s.*)
                             \.
                             (pdf|djvu|ps)
                         )
                         """ % q_rgx, re.X|re.I)
        matches = []
        for f in files:
            m = rgx.match(f)
            if m:
                d = m.groupdict()
                file_name_safe = urllib.parse.quote_plus(d['file_name'])
                matches.append(file_name_safe)
        return json.dumps(matches, indent=2)

    def do_open(self, query):
        file_name = urllib.parse.unquote_plus(query)
        file_path = os.path.join("/Users/roi/Google Drive/Zotero", file_name)
        if os.path.exists(file_path):
            subprocess.call(["open", file_path])

    def do_view(self, query):
        file_path = urllib.parse.unquote_plus(query)
        self.queue.put(["view", file_path])

    def do_synctex_forward_search(self, query):
        args = urllib.parse.parse_qs(query)
        try:
            pdf = args["pdf"][0]
            tex = args["tex"][0]
            col = int(args["col"][0])
            line = int(args["line"][0])
        except:
            return
        self.queue.put(["synctex_forward_search", pdf, tex, line, col])

start_pulp_server = PulpServer.start_multiprocess

if __name__ == "__main__":
    proc = PulpServer.start_multiprocess()
    proc.join()
