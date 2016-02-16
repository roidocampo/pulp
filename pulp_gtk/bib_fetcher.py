#!/usr/bin/env python3

import base64
import collections
import concurrent.futures
import functools
import gi
import glob
import html.entities
import os
import os.path
import re
import subprocess
import sys
import threading
import unidecode
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

############################################################

def memoized_property(fget):
    attr_name = '_{0}'.format(fget.__name__)

    @functools.wraps(fget)
    def fget_memoized(self):
        if not hasattr(self, attr_name):
            setattr(self, attr_name, fget(self))
        return getattr(self, attr_name)

    return property(fget_memoized)

############################################################

def unescape(text):
    def fixup(m):
        text = m.group(0)
        if text[:2] == "&#":
            # character reference
            try:
                if text[:3] == "&#x":
                    return chr(int(text[3:-1], 16))
                else:
                    return chr(int(text[2:-1]))
            except ValueError:
                pass
        else:
            # named entity
            try:
                text = chr(html.entities.name2codepoint[text[1:-1]])
            except KeyError:
                pass
        return text # leave as is
    return re.sub("&#?\w+;", fixup, text)

############################################################

class BibFetcher:

    ########################################################
    # Guess data for one file
    ########################################################

    def __init__(self, path):
        self.original_path = path
        self.path = path
        self.filename = os.path.basename(self.path)

    rgx = re.compile(r"""
                     ^
                     (?P<basename>
                         (?P<authors> .+)
                         _
                         (?P<year> \d\d\d\d)?
                         _
                         (?P<title> .+)
                     )
                     \.
                     (?P<extension> pdf|djvu|ps)
                     $
                     """, re.X)

    @memoized_property
    def rgx_match_or_arxiv(self):
        m = self.rgx.match(self.filename)
        if not m:
            if self.arxiv_id_from_pdf is not None:
                cpath = self.arxiv_canonical_path
                if cpath is not None:
                    self.path = cpath
                    self.filename = cpath
                    m = self.rgx.match(self.filename)
        return m

    @memoized_property
    def data(self):
        m = self.rgx_match_or_arxiv
        if m:
            return m.groupdict()
        else:
            return {}

    @memoized_property
    def is_good(self):
        try:
            self.data['basename']
        except KeyError:
            return False
        else:
            return True

    @memoized_property
    def basename(self):
        if self.is_good:
            return self.data['basename']
        else:
            return os.path.splitext(self.filename)[0]

    @memoized_property
    def extension(self):
        return self.data['extension']

    @memoized_property
    def authors(self):
        au = self.data['authors']
        #print(au)
        au = re.sub(r'(^|_)(de|Du)_', r'\1\2 ', au)
        #au = au.replace('de_', 'de ')
        au = au.split('_')
        return au
        
    @memoized_property
    def year(self):
        return self.data['year']

    @memoized_property
    def title(self):
        title = self.data['title']
        return title.replace('_', ' ')

    @memoized_property
    def safe_title(self):
        safe = ""
        for c in self.title:
            if c == "$":
                break
            else:
                safe += c
        return safe

    @memoized_property
    def short_title(self):
        short = self.safe_title.split()
        short = " ".join(short[:5])
        return short

    @memoized_property
    def title_set(self):
        ts = self.safe_title.split()
        return set(unidecode.unidecode(t) for t in ts)

    ########################################################
    # Fetch all the bibtex
    ########################################################

    @memoized_property
    def bibtex(self):
        if not self.is_good:
            bib = [self.bibtex_head,
                   self.msn_not_found,
                   self.zbmath_not_found,
                   self.arxiv_not_found]
        else:
            bib = [self.bibtex_head,
                   self.msn_bib,
                   self.zbmath_bib,
                   self.arxiv_bib]
        return "\n".join(bib)

    @memoized_property
    def bibtex_head(self):
        return "% {}\n".format(self.filename)

    @property
    def bib_status(self):
        return (self.msn_status 
                + self.zbmath_status 
                + self.arxiv_status
                + self.per_status)

    ########################################################
    # Fetch MathSciNet bibtex
    ########################################################

    msn_not_found = "% No MathSciNet entry found.\n"
    msn_status = " "

    @memoized_property
    def msn_bib(self):
        bibs = self.msn_bib_bibtex(True)
        if bibs:
            bibs += self.msn_bib_amsrefs(True)
        elif self.year is not None:
            bibs = self.msn_bib_bibtex(False)
            if bibs:
                bibs += self.msn_bib_amsrefs(False)
        if bibs:
            self.msn_status = "M"
            bib = "\n".join(bibs)
            bib = re.sub(r"@(\w+) {MR", r"@\1{MR", bib)
            bib = re.sub(
                r"^\s*(\w+)\s+=\s+", 
                lambda m: m.group(0).lower(), 
                bib, flags=re.M)
            return bib
        else:
            self.msn_status = "-"
            return self.msn_not_found

    msn_rgx_bibtex = re.compile(r"^@.*?^}", re.M | re.S)
    msn_rgx_amsrefs = re.compile(r"^\\bib.*?^}", re.M | re.S)

    def msn_bib_bibtex(self, use_year):
        return self.msn_bib_aux("bibtex", self.msn_rgx_bibtex, use_year)

    def msn_bib_amsrefs(self, use_year):
        return self.msn_bib_aux("amsrefs", self.msn_rgx_amsrefs, use_year)

    def msn_bib_aux(self, fmt, regex, use_year):
        url = self.msn_url(fmt, use_year)
        html = self.get_html(url, use_proxy=True)
        if not html:
            return []
        bibs = re.findall(regex, html)
        if bibs:
            return [ bib+"\n" for bib in bibs ]
        else:
            return []

    msn_root = "http://www.ams.org/mathscinet/search/publications.html?fmt="

    def msn_url(self, fmt, use_year=True):
        if use_year:
            return self.msn_root + fmt + self.msn_query_year
        else:
            return self.msn_root + fmt + self.msn_query

    @memoized_property
    def msn_query(self):
        return self.msn_query_aux[0]

    @memoized_property
    def msn_query_year(self):
        return self.msn_query_aux[1]

    @memoized_property
    def msn_query_aux(self):
        query = ""
        tmpl = "&pg{num}={key}&s{num}={val}".format
        title = urllib.parse.quote(self.short_title)
        query += tmpl(num=1, key='TI', val=title)
        for n, author in enumerate(self.authors, 3):
            author = urllib.parse.quote(author)
            query += tmpl(num=n, key='AUCN', val=author)
        year_query = query
        if self.year is not None:
            year_query += tmpl(num=2, key='YR', val=self.year)
        return query, year_query

    ########################################################
    # Fetch zbMATH bibtex
    ########################################################

    zbmath_not_found = "% No zbMATH entry found.\n"
    zbmath_status = " "

    @memoized_property
    def zbmath_bib(self):
        html = self.get_html(self.zbmath_url_year)
        if not html:
            self.zbmath_status = "-"
            return self.zbmath_not_found
        m = re.search(r"bibtex/(\d|\.)+\.bib", html)
        if not m:
            html = self.get_html(self.zbmath_url)
            if not html:
                self.zbmath_status = "-"
                return self.zbmath_not_found
            m = re.search(r"bibtex/(\d|\.)+\.bib", html)
        if not m:
            self.zbmath_status = "-"
            return self.zbmath_not_found
        else:
            bib_url = "https://zbmath.org/" + m.group(0)
            bib = self.get_html(bib_url)
            if bib:
                self.zbmath_status = "Z"
                return bib + "\n"
            else:
                self.zbmath_status = "-"
                return self.zbmath_not_found

    @memoized_property
    def zbmath_url_year(self):
        url = []
        tmpl = "{key}: {val}".format
        title = urllib.parse.quote(self.safe_title)
        url.append(tmpl(key='ti', val=title))
        if self.year is not None:
            url.append(tmpl(key='py', val=self.year))
        url.append(tmpl(key='au', val=self.zbmath_author_aux))
        url = " %26 ".join(url)
        url = "https://zbmath.org/?q=" + url
        return url

    @memoized_property
    def zbmath_url(self):
        url = []
        tmpl = "{key}: {val}".format
        title = urllib.parse.quote(self.safe_title)
        url.append(tmpl(key='ti', val=title))
        url.append(tmpl(key='au', val=self.zbmath_author_aux))
        url = " %26 ".join(url)
        url = "https://zbmath.org/?q=" + url
        return url

    @memoized_property
    def zbmath_author_aux(self):
        authors = []
        for au in self.authors:
            au2 = au.replace(" ","")
            if au == au2:
                authors.append(au)
            else:
                authors.append("({}|{})".format(au, au2))
        authors = [urllib.parse.quote(author) for author in authors]
        return " ".join(authors)

    ########################################################
    # Fetch arXiv bibtex
    ########################################################

    arxiv_not_found = "% No arXiv entry found.\n"
    arxiv_status = " "

    @memoized_property
    def arxiv_bib(self):
        if self.arxiv_id is None:
            self.arxiv_status = "-"
        else:
            self.arxiv_status = "A"
        return self.arxiv_bib_aux

    @memoized_property
    def arxiv_id(self):
        arxiv_id = self.arxiv_id_from_pdf
        if arxiv_id is None:
            arxiv_id = self.get_arxiv_id_from_web()
        return arxiv_id

    @memoized_property
    def arxiv_id_from_pdf(self):
        with open(self.path, "r", encoding="latin-1") as pdffile:
            pdfdata = pdffile.read()
        m = re.search(r"/URI\(http://ar[Xx]iv.org/abs/(.+)\)", pdfdata)
        if not m:
            return None
        else:
            return m.group(1)

    arxiv_rgx = re.compile(r"""
                           < (?P<type> id|title ) >
                           (?:
                               (?:
                                   http://arxiv\.org/abs/
                                   (?P<arxiv_id> .*? )
                                   (?: v\d+ )?
                               )
                               |
                               (?P<title> .*? )
                           )
                           </ (?P=type) >
                           """, re.X)

    def title_match(self, other_title):
        ots = other_title.split()
        ots = set(unidecode.unidecode(t) for t in ots)
        inter = ots.intersection(self.title_set)
        goal = min(6, len(ots), len(self.title_set))
        return len(inter) >= goal

    def get_arxiv_id_from_web(self):
        atom = self.get_html(self.arxiv_atom_url)
        if not atom:
            return None
        arxiv_id = ""
        for m in self.arxiv_rgx.finditer(atom):
            md = m.groupdict()
            if md['type'] == 'id':
                arxiv_id = md['arxiv_id']
            elif arxiv_id and self.title_match(md['title']):
                return arxiv_id

    @memoized_property
    def arxiv_atom_url(self):
        queries = []
        tmpl = "{key}:{val}".format
        title = unidecode.unidecode(self.safe_title)
        title = urllib.parse.quote(title)
        queries.append(tmpl(key='ti', val=title))
        for author in self.authors:
            author = unidecode.unidecode(author)
            author = urllib.parse.quote(author)
            queries.append(tmpl(key='au', val=author))
        root = "http://export.arxiv.org/api/query?search_query="
        query = "+AND+".join(queries)
        return root + query

    @memoized_property
    def arxiv_data(self):
        if self.arxiv_id is None:
            return {}
        url = "http://arxiv.org/abs/" + self.arxiv_id
        html = self.get_html(url)
        regex = r"<meta\s*name=\"citation_(%s)\"\s*content=\"(.*)\"\s*/>"
        regex = regex % "title|author|date|arxiv_id|pdf_url|doi"
        data = {}
        for line in html.split("\n"):
            m = re.match(regex, line)
            if m:
                key = m.group(1)
                content = m.group(2)
                if key == "author" or key == "title":
                    content = unescape(content)
                if key == "author" and "author" in data:
                    data["author"] += " and " + content
                elif key == "arxiv_id":
                    data["archivePrefix"] = "arXiv"
                    data["eprint"] = content
                elif key == "pdf_url":
                    data["pdf_url"] = content
                    content = content.replace("pdf", "abs", 1)
                    data["url"] = content
                else:
                    data[key] = content
        return data

    @memoized_property
    def arxiv_bib_aux(self):
        if self.arxiv_id is None:
            return self.arxiv_not_found
        data = self.arxiv_data.copy()
        if "eprint" in data:
            bibtex = "@article{arXiv:%s,\n" % data["eprint"]
        else:
            bibtex = "@article{arXiv:ERROR,\n"
        for key in "author", "title", "date", "archivePrefix", "eprint":
            if key in data:
                val = data[key]
                bibtex += "    %s = {%s},\n" % (key, val)
                del data[key]
        for key,val in data.items():
            bibtex += "    %s = {%s},\n" % (key, val)
        bibtex += "}\n"
        return bibtex

    @memoized_property
    def arxiv_canonical_path(self):
        if self.arxiv_id is None:
            return None
        data = self.arxiv_data.copy()
        if "author" not in data:
            return None
        if "title" not in data:
            return None
        authors = data["author"].split(" and ")
        authors = [ au.split(",")[0] for au in authors ]
        authors = "_".join(authors)
        if "date" in data:
            year = data["date"][:4]
        else:
            year = ""
        title = data["title"]
        cpath = authors + "_" + year + "_" + title + ".pdf"
        cpath = cpath.replace(" ", "_")
        return cpath

    ########################################################
    # Personal bibtex entries
    ########################################################

    @memoized_property
    def personal_bib(self):
        if not self.personal_bib_exists:
            return ""
        with open(self.personal_bib_path, encoding="utf-8") as pfile:
            return pfile.read()

    @memoized_property
    def personal_bib_path(self):
        home = os.path.expanduser("~")
        pdir = os.path.join(home, ".pulp-bib", "personal")
        return os.path.join(pdir, self.basename + ".bib")

    @memoized_property
    def personal_bib_exists(self):
        return os.path.exists(self.personal_bib_path)

    def save_personal_bib(self, pbib):
        pdir = os.path.dirname(self.personal_bib_path)
        if not os.path.exists(pdir):
            os.makedirs(pdir)
        with open(self.personal_bib_path, "w", encoding="utf-8") as pfile:
            pfile.write(pbib)
        self._personal_bib_exists = True
        self._personal_bib = pbib

    ########################################################
    # Cache of bibtex entries
    ########################################################

    @memoized_property
    def cache_bib(self):
        if not self.cache_bib_exists:
            return ""
        with open(self.cache_bib_path, encoding="utf-8") as cfile:
            return cfile.read()

    @memoized_property
    def cache_bib_path(self):
        home = os.path.expanduser("~")
        cdir = os.path.join(home, ".pulp-bib", "cache")
        return os.path.join(cdir, self.basename + ".bib")

    @memoized_property
    def cache_bib_exists(self):
        return os.path.exists(self.cache_bib_path)

    def save_cache_bib(self, bib=None):
        cdir = os.path.dirname(self.cache_bib_path)
        if not os.path.exists(cdir):
            os.makedirs(cdir)
        if bib == None:
            bib = self.bibtex
        with open(self.cache_bib_path, "w", encoding="utf-8") as cfile:
            cfile.write(bib)
        self._cache_bib_exists = True
        self._cache_bib = bib

    ########################################################
    # Url opener with proxy
    ########################################################
    
    def get_html(self, url, use_proxy=False):
        url = url.replace(' ', '%20')
        req = urllib.request.Request(url)
        if use_proxy:
            self.add_proxy(req)
        for try_num in range(10):
            try:
                handle = urllib.request.urlopen(req)
            except:
                handle = None
                continue
            else:
                break
        if handle is None:
            return
        enc = handle.headers.get_content_charset()
        html = handle.read()
        html = html.decode(enc)
        return html

    def add_proxy(self, req):
        req.set_proxy("proxy.csic.es:3128", req.type)
        authheader = "Basic MzQ5OTAzNTVIOkY1ZzhyNGUz"
        req.add_header("Proxy-Authorization", authheader)

############################################################

class ThreadedBibFetcher:

    def __init__(self, path):
        self.path = path
        self.bib_fetcher = None
        self.worker_done = False
        self.worker_running = False
        self.first_callbacks = []
        self.callbacks = []

    def check_fetcher(self):
        if self.bib_fetcher is None:
            self.bib_fetcher = BibFetcher(self.path)

    def run_thread(self):
        if self.worker_running:
            return
        self.worker_running = True
        thread = threading.Thread(
            target = self.thread_worker,
            args = (self.bib_fetcher,),
            daemon = True)
        thread.start()

    def thread_worker(self, fetcher):
        cache_bib = fetcher.cache_bib
        personal_bib = fetcher.personal_bib
        GLib.idle_add(self.worker_first_callback)
        bibtex = fetcher.bibtex
        fetcher.save_cache_bib()
        GLib.idle_add(self.worker_first_callback)
        GLib.idle_add(self.worker_callback)

    def worker_first_callback(self):
        while self.first_callbacks:
            cb, args = self.first_callbacks.pop(0)
            GLib.idle_add(cb, 
                          self.bib_fetcher.cache_bib, 
                          self.bib_fetcher.personal_bib, 
                          *args)

    def worker_callback(self):
        self.worker_done = True
        while self.callbacks:
            cb, args = self.callbacks.pop(0)
            GLib.idle_add(cb, self.bib_fetcher.bibtex, *args)

    def async_get_bibtex(self, first_callback, callback, *args):
        self.check_fetcher()
        if self.worker_done:
            GLib.idle_add(first_callback, 
                          self.bib_fetcher.cache_bib, 
                          self.bib_fetcher.personal_bib, 
                          *args)
            GLib.idle_add(callback, 
                          self.bib_fetcher.bibtex, 
                          *args)
        else:
            self.first_callbacks.append([first_callback, args])
            self.callbacks.append([callback, args])
            self.run_thread()

    def save_personal_bib(self, pbib):
        self.check_fetcher()
        self.bib_fetcher.save_personal_bib(pbib)
