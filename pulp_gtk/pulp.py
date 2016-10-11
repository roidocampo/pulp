#!/usr/bin/env python3

########################################################################
# Libraries
########################################################################

import ast
import base64
import collections
import gi
import os
import pkg_resources
import random
import re
import shutil
import subprocess
import sys
import time
import tempfile
import webbrowser

gi.require_version('Gtk', '3.0')
gi.require_version('EvinceDocument', '3.0')
gi.require_version('EvinceView', '3.0')
gi.require_version('GtkosxApplication', '1.0')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Pango
from gi.repository import GtkosxApplication
from gi.repository import EvinceDocument
from gi.repository import EvinceView

from . import bib_fetcher
from . import bib_window
from . import pulp_server


########################################################################
# Convenience dot-notation dictionary
########################################################################

class AttrDict(dict):
    def __getattr__(self, name):
        return self[name]
    def __setattr__(self, name, value):
        self[name] = value

########################################################################
# Convenience Resources Class
########################################################################

class Resource(object):

    @staticmethod
    def string(name):
        return pkg_resources.resource_string(__name__, name)

    @staticmethod
    def filename(name):
        return pkg_resources.resource_filename(__name__, name)

########################################################################
# Applescript print script
########################################################################

PRINT_SCRIPT = """

tell application "{app}"
    activate
    open POSIX file "{path}"
    repeat until application "{app}" is frontmost
        delay .01
    end repeat
    tell application "System Events"
        keystroke "p" using command down
    end tell
end tell

"""

########################################################################
# Debug opened file descriptors
########################################################################

class FdsDebug:

    instance = None

    def __init__(self):
        # Debugging disabled
        return
        self.fds = []
        self.update_fds()
        GLib.timeout_add(100, self.update_fds)
        FdsDebug.instance = self

    @classmethod
    def log(cls, *args):
        if cls.instance is not None:
            print(*args)

    def update_fds(self):
        '''
        return the number of open file descriptors for current process

        .. warning: will only work on UNIX-like os-es.
        '''
        pid = os.getpid()
        procs = subprocess.check_output( 
            [ "lsof", '-w', '-Ffn', "-p", str( pid ) ] )

        new_fds = []
        detecting_name = False

        for field in procs.split(b'\n'):
            if not field:
                continue
            f_type, f_data = field[0:1], field[1:]
            if f_type == b'f' and f_data.isdigit():
                new_fds.append([int(f_data), "???"])
                detecting_name = True
            elif detecting_name and f_type == b'n':
                name_literal = f_data.decode("utf-8")
                name_literal.replace('"', '\\"')
                name_literal = 'b"' + name_literal + '"'
                name = ast.literal_eval(name_literal)
                name = name.decode("utf-8")
                new_fds[-1][-1] = name
            else:
                detecting_name = False

        fd_closed = []
        fd_opened = []
        for fd in self.fds:
            if fd not in new_fds:
                fd_closed.append(fd)
        for fd in new_fds:
            if fd not in self.fds:
                fd_opened.append(fd)
        if fd_closed:
            fd_closed = " ".join(map(lambda x: str(x[0]), fd_closed))
            print("- %s" % (fd_closed))
        if fd_opened:
            for fd, fd_name in fd_opened:
                print("+ %s %s" % (fd, repr(fd_name.encode('utf-8'))))

        self.fds = new_fds
        return True

########################################################################
# PulpWindow Class
########################################################################

class PulpWindow(Gtk.ApplicationWindow):

    ####################################################################
    # Class Initialization
    ####################################################################
    
    __gtype_name__ = 'PulpWindow'

    template = None
    template_fields = ["stack", 
                       "sidebar_treeview", 
                       "sidebar_model", 
                       "search_stack", 
                       "pages_label", 
                       "nada" ]

    def __new__(cls, *args, **kws):
        if cls.template is None:
            cls.template = Resource.string("ui_window.xml")
            cls.set_template(GLib.Bytes(cls.template))
            for field in cls.template_fields:
                cls.bind_template_child_full(field, True, 0)
            EvinceDocument.init()
        return super().__new__(cls)

    ####################################################################
    # Instance Initialization
    ####################################################################
    
    def __init__(self, app):
        super().__init__(application = app)
        self.app = app
        self.init_misc()
        self.init_template()
        self.init_fields()
        self.init_actions()
        self.init_fullscreen()

    def init_fields(self):
        for field in self.template_fields:
            child = self.get_template_child(self.__class__, field)
            self.__dict__[field] = child
        self.sidebar_treeview.connect(
            'cursor-changed', 
            self.sidebar_selection_changed)

    def init_actions(self):
        def add_simple_action(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
        add_simple_action("duplicate", self.on_action_duplicate)
        add_simple_action("close", self.on_action_close)
        add_simple_action("undoclose", self.on_action_undo_close)
        add_simple_action("preview", self.on_action_preview)
        add_simple_action("print", self.on_action_print)
        add_simple_action("copy", self.on_action_copy)
        add_simple_action("zoomin", self.on_action_zoom_in)
        add_simple_action("zoomout", self.on_action_zoom_out)
        add_simple_action("zoom100", self.on_action_zoom_100)
        add_simple_action("zoomfitwidth", self.on_action_zoom_fit_width)
        add_simple_action("zoomfitpage", self.on_action_zoom_fit_page)
        add_simple_action("find", self.on_action_find)
        add_simple_action("findnext", self.on_action_find_next)
        add_simple_action("findprevious", self.on_action_find_previous)
        add_simple_action("goto", self.on_action_goto)
        add_simple_action("gonext", self.on_action_go_next)
        add_simple_action("goprevious", self.on_action_go_previous)
        add_simple_action("movetabup", self.on_action_move_tab_up)
        add_simple_action("movetabdown", self.on_action_move_tab_down)
        add_simple_action("bibtex", self.on_action_bibtex)
        add_simple_action("singlepage", self.on_action_single_page)
        add_simple_action("fullscreen", self.on_action_fullscreen)
        add_simple_action("quit", self.on_action_quit)

    def init_misc(self):
        self.in_dialog = False
        self.doc_views = {}
        self.close_history = []
        self.open_count = 0
        self.in_search_entry_keypress = False
        self.tempdir = self.app.tempdir

    def init_fullscreen(self):
        self.geometry_restore = AttrDict(
            pos=(50,50), size=(800, 500), decorated=True)
        screen = Gdk.Screen.get_default()
        print("Scale factor:", self.get_scale_factor())
        import os
        print(os.environ)
        max_width = screen.width()
        max_height = screen.height()
        self.geometry_fullscreen = AttrDict(
            pos=(0, 23), size=(max_width, max_height-23),
            decorated=False)
        if max_width > 2000:
            self.geometry_restore = AttrDict(
                pos=(max_width/2-5,50), size=(max_width/2, max_height-55), decorated=True)
            self.fullscreen = True
        else:
            self.fullscreen = None
        self.on_action_fullscreen()

    ####################################################################
    # Quit
    ####################################################################

    def on_action_quit(self, action, parameter):
        if self.in_dialog:
            return
        doc_view = self.get_current_doc_view()
        if doc_view is None:
            self.app.quit()
            return
        self.in_dialog = True
        dialog = Gtk.MessageDialog(self, 0, 
                                   Gtk.MessageType.WARNING,
                                   Gtk.ButtonsType.YES_NO, 
                                   "\nAre you sure you want to quit this Pulp window?")
        dialog.format_secondary_text(
            "There are several documents opened.")
        response = dialog.run()
        dialog.destroy()
        self.in_dialog = False
        if response == Gtk.ResponseType.YES:
            self.close()
            self.app.remove_window(self)
            self.app.quit_if_needed()

    ####################################################################
    # Go to page
    ####################################################################

    def on_action_goto(self, action, parameter):
        if self.in_dialog:
            return
        doc_view = self.get_current_doc_view()
        if doc_view is None:
            return
        self.in_dialog = True
        dialog = Gtk.MessageDialog(self, 0, 
                                   Gtk.MessageType.WARNING,
                                   Gtk.ButtonsType.OK_CANCEL, 
                                   "\nGo To Page")
        dialog.format_secondary_text(
            "Choose the page you want to go to:")
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_message_area()
        page_num = doc_view.model.get_page()+1
        tot_pages = doc_view.model.get_document().get_n_pages()
        adjust = Gtk.Adjustment(page_num,1,tot_pages+1,1,1,1)
        spin = Gtk.SpinButton.new(adjust, 1, 0)
        spin.set_value(page_num)
        box.add(spin)
        dialog.show_all()
        def spin_activate(*args):
            dialog.response(Gtk.ResponseType.OK)
            dialog.close()
        spin.connect("activate", spin_activate)
        response = dialog.run()
        new_page_num = spin.get_value()
        dialog.destroy()
        self.in_dialog = False
        if response == Gtk.ResponseType.OK:
            if page_num != new_page_num:
                doc_view.model.set_page(new_page_num-1)
                self.history_save(doc_view)

    ####################################################################
    # Fullscreen/Restore
    ####################################################################

    def on_action_fullscreen(self, action=None, parameter=None):
        if self.fullscreen:
            self.fullscreen = False
            self.set_geometry(self.geometry_restore)
        else:
            if self.fullscreen is not None:
                self.geometry_restore = self.get_geometry()
            self.fullscreen = True
            self.set_geometry(self.geometry_fullscreen)

    def set_geometry(self, geom):
        self.set_decorated(geom.decorated)
        self.move(*geom.pos)
        self.resize(*geom.size)
    
    def get_geometry(self):
        return AttrDict(
            decorated = self.get_decorated(),
            pos = self.get_position(),
            size = self.get_size())

    ####################################################################
    # Open File
    ####################################################################
    
    def open_file(self, file_path, orig_doc_view=None, at_end=False):
        FdsDebug.log("OPEN", repr(file_path.encode('utf-8')))
        doc_view = self.create_doc_view(file_path, orig_doc_view)
        self.insert_in_sidebar(doc_view, at_end)
        self.sync(doc_view, orig_doc_view)

    def create_doc_view(self, path, orig_doc_view=None):
        orig_path = path
        name, title, mime, mime_name, bib_path = self.process_path(path)
        doc, path = self.load_doc(mime, path, orig_doc_view)

        box = Gtk.Box()
        scroll = Gtk.ScrolledWindow()
        view = EvinceView.View()
        model = EvinceView.DocumentModel()
        search_entry = Gtk.SearchEntry()
        # bibtex_container = Gtk.Frame()
        # bibtex_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        # bibtex_scroll = Gtk.ScrolledWindow()
        # bibtex_text = Gtk.TextView()
        # bibtex_flow = Gtk.FlowBox()
        # bibtex_space = Gtk.Label("")
        # # bibtex_button = Gtk.Button.new_with_label("Edit")

        model.set_document(doc)
        view.set_model(model)
        scroll.add(view)
        # bibtex_scroll.add(bibtex_text)
        # # bibtex_flow.add(bibtex_button)
        # bibtex_box.pack_start(bibtex_flow, False, True, 0)
        # bibtex_box.pack_start(bibtex_space, False, True, 0)
        # bibtex_box.pack_start(bibtex_scroll, True, True, 0)
        # bibtex_container.add(bibtex_box)
        box.pack_start(scroll, True, True, 0)
        # box.pack_start(bibtex_container, True, True, 0)
        self.search_stack.add_named(search_entry, name)
        self.stack.add_titled(box, name, title)

        view.find_set_highlight_search(True)
        # bibtex_text.set_monospace(True)
        # bibtex_text.set_editable(False)
        # bibtex_text.get_buffer().set_text("Loading BibTeX...")
        # bibtex_container.get_style_context().add_class("bibtex-container")

        doc_view = AttrDict(
            view=view, model=model, doc=doc, box=box, 
            # bibtex_container=bibtex_container,
            # bibtex_text=bibtex_text, # bibtex_button=bibtex_button,
            scroll=scroll, search_entry=search_entry,
            name=name, title=title, path=path, orig_path=orig_path,
            mime=mime, mime_name=mime_name,
            bib_path=bib_path,
            bib_fetcher=bib_fetcher.ThreadedBibFetcher(orig_path),
            find_job=None, history=[(0.0,0.0)], history_pos=0)

        self.doc_views[name] = doc_view
        view.connect("handle-link", self.handle_link, doc_view)
        view.connect("external-link", self.external_link)
        model.connect("page-changed", self.page_changed, doc_view)
        view.connect('key-press-event', self.keypress_view)
        search_entry.connect('search-changed', self.search_changed, doc_view)
        search_entry.connect('stop-search', self.on_action_find_clear)
        # bibtex_container.connect('show', self.load_bibtex, doc_view)

        search_entry.show()
        box.show()
        # bibtex_box.show_all()
        scroll.show_all()

        return doc_view

    def process_path(self, path):
        self.open_count += 1
        name = str(self.open_count)
        base, filename = os.path.split(path)
        filename, ext = os.path.splitext(filename)
        bib_path = os.path.join(base, "bib", filename + ".bib")
        title = filename.replace("_", " ")
        if ext == ".djvu":
            mime = 'image/vnd.djvu'
            mime_name = "DjVu"
        elif ext == ".ps":
            mime = 'application/postscript'
            mime_name = "PS"
        elif ext == ".dvi":
            mime = 'application/x-dvi'
            mime_name = "DVI"
        else:
            mime = 'application/pdf'
            mime_name = "PDF"
        return name, title, mime, mime_name, bib_path

    def load_doc(self, mime, path, orig_doc_view=None):
        if mime != 'image/vnd.djvu':
            try:
                doc = EvinceDocument.backends_manager_get_document(mime)
                doc.load('file://' + path)
                return doc, path
            except:
                pass
        safe_path = ''.join([random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8)])
        safe_path += str(int(time.time()*1000000)) + "z"
        safe_path = os.path.join(self.tempdir, safe_path)
        if mime == 'application/x-dvi':
            if orig_doc_view is None:
                env = os.environ.copy()
                env['PATH'] = '/usr/local/bin:' + env['PATH'] + ':/Library/TeX/texbin'
                subprocess.call(('dvipdf', path, safe_path), env=env)
            else:
                os.symlink(orig_doc_view.path, safe_path)
            mime = 'application/pdf'
        else:
            os.symlink(path, safe_path)
        doc = EvinceDocument.backends_manager_get_document(mime)
        doc.load('file://' + safe_path)
        return doc, safe_path

    def insert_in_sidebar(self, dv, at_end=False):
        cursor, col = self.sidebar_treeview.get_cursor()
        if (not at_end) and cursor:
            itr = self.sidebar_model.get_iter(cursor)
            itr = self.sidebar_model.insert_after(
                itr, [dv.title, dv.name])
        else:
            itr = self.sidebar_model.append([dv.title, dv.name])
        pth = self.sidebar_model.get_path(itr)
        self.sidebar_treeview.set_cursor(pth)
        self.sidebar_selection_changed()

    def sync(self, doc_view, orig_doc_view):
        if orig_doc_view is not None:
            if 'sync_data' in orig_doc_view:
                doc_view.model.set_sizing_mode(
                    orig_doc_view.sync_data.sizing_mode)
                doc_view.model.set_scale(
                    orig_doc_view.sync_data.scale)
                place=(
                   orig_doc_view.sync_data.hadjustment,
                   orig_doc_view.sync_data.vadjustment)
            else:
                doc_view.model.set_sizing_mode(
                    orig_doc_view.model.get_sizing_mode())
                doc_view.model.set_scale(
                    orig_doc_view.model.get_scale())
                place=(
                   orig_doc_view.scroll.get_hadjustment().get_value(),
                   orig_doc_view.scroll.get_vadjustment().get_value())
            def later(*args):
                if doc_view.view.is_loading():
                    return True
                doc_view.history_pos += 1
                doc_view.history.append(place)
                doc_view.scroll.get_hadjustment().set_value(place[0])
                doc_view.scroll.get_vadjustment().set_value(place[1])
                new_place=(
                   doc_view.scroll.get_hadjustment().get_value(),
                   doc_view.scroll.get_vadjustment().get_value())
                if new_place!=place:
                    return True
            GLib.timeout_add(10, later)
    
    ####################################################################
    # Close document
    ####################################################################
    
    def on_action_close(self, *args):
        cursor, col = self.sidebar_treeview.get_cursor()
        if cursor:
            itr = self.sidebar_model.get_iter(cursor)
            name = self.sidebar_model.get_value(itr, 1)
            self.sidebar_model.remove(itr)
            if name in self.doc_views:
                doc_view = self.doc_views[name]
                self.create_close_history_item(doc_view)
                FdsDebug.log("CLOSE", repr(doc_view.path.encode("utf-8")))
                if self.check_doc_view_path_is_unique(doc_view):
                    self.close_file_descriptor(doc_view.path)
                self.stack.remove(doc_view.view)
                del self.doc_views[name]
                if not self.doc_views:
                    self.stack.set_visible_child(self.nada)
                    self.pages_label.set_text('')
        self.sidebar_selection_changed()

    def create_close_history_item(self, doc_view):
        hi = AttrDict(
            orig_path = doc_view.orig_path,
            path = doc_view.path,
            sync_data = AttrDict(
                sizing_mode = doc_view.model.get_sizing_mode(),
                scale = doc_view.model.get_scale(),
                hadjustment = doc_view.scroll.get_hadjustment().get_value(),
                vadjustment = doc_view.scroll.get_vadjustment().get_value()
            )
        )
        self.close_history.append(hi)

    def check_doc_view_path_is_unique(self, doc_view):
        count = 0
        for other_view in self.doc_views.values():
            if other_view.path == doc_view.path:
                count += 1
        if count == 1:
            return True
        else:
            return False

    def close_file_descriptor(self, path):
        pid = os.getpid()
        procs = subprocess.check_output( 
            [ "lsof", '-w', '-Ffn', "-p", str( pid ) ] )

        fds = []
        detecting_name = False

        for field in procs.split(b'\n'):
            if not field:
                continue
            f_type, f_data = field[0:1], field[1:]
            if f_type == b'f' and f_data.isdigit():
                fds.append([int(f_data), "???"])
                detecting_name = True
            elif detecting_name and f_type == b'n':
                name_literal = f_data.decode("utf-8")
                name_literal.replace('"', '\\"')
                name_literal = 'b"' + name_literal + '"'
                name = ast.literal_eval(name_literal)
                name = name.decode("utf-8")
                fds[-1][-1] = name
            else:
                detecting_name = False

        for fd, name in fds:
            if name==path:
                os.close(fd)

    ####################################################################
    # Undo close document
    ####################################################################
    
    def on_action_undo_close(self, *args):
        if self.close_history:
            hi = self.close_history.pop()
            self.open_file(hi.orig_path, hi)

    ####################################################################
    # Get current doc_view
    ####################################################################

    def get_current_doc_view(self):
        current_name = self.stack.get_visible_child_name()
        if current_name in self.doc_views:
            doc_view = self.doc_views[current_name]
            return doc_view
        else:
            return None
    
    ####################################################################
    # Change selection in sidebar
    ####################################################################
    
    def sidebar_selection_changed(self, tree_view=None):
        cursor, col = self.sidebar_treeview.get_cursor()
        if cursor:
            itr = self.sidebar_model.get_iter(cursor)
            name = self.sidebar_model.get_value(itr, 1)
            self.stack.set_visible_child_name(name)
            self.search_stack.set_visible_child_name(name)
            if name in self.doc_views:
                doc_view = self.doc_views[name]
                self.page_changed(doc_view)
                def later():
                    doc_view.view.grab_focus()
                GLib.timeout_add(1, later)

    ####################################################################
    # Update page number
    ####################################################################
    
    def page_changed(self, *args):
        doc_view = args[-1]
        # page_num = doc_view.model.get_page()+1
        # tot_pages = doc_view.model.get_document().get_n_pages()
        self.pages_label.set_text(
            "%s - Page %s of %s" % (
                doc_view.mime_name,
                doc_view.model.get_page()+1,
                doc_view.model.get_document().get_n_pages(),
            ))

    ####################################################################
    # Open external links in browser
    ####################################################################
    
    def external_link(self, widget, o):
        link_type = o.get_action_type()
        if link_type == EvinceDocument.LinkActionType.EXTERNAL_URI:
            webbrowser.open(o.get_uri())
        elif link_type == EvinceDocument.LinkActionType.LAUNCH:
            filepath = o.get_filename()
            if sys.platform.startswith('darwin'):
                subprocess.call(('open', filepath))
            elif os.name == 'nt':
                os.startfile(filepath)
            elif os.name == 'posix':
                subprocess.call(('xdg-open', filepath))

    ####################################################################
    # Update history after internal link
    ####################################################################
    
    def handle_link(self, widget, o, doc_view):
        self.history_save(doc_view)

    def history_save(self, doc_view):
        history = doc_view.history
        pos = doc_view.history_pos
        del history[pos+1:]
        p = (doc_view.scroll.get_hadjustment().get_value(),
             doc_view.scroll.get_vadjustment().get_value())
        if (p != history[pos]):
            doc_view.history_pos += 1
            history.append(p)
        def later():
            doc_view.history_pos += 1
            history.append((
                doc_view.scroll.get_hadjustment().get_value(),
                doc_view.scroll.get_vadjustment().get_value()))
        GLib.timeout_add(100, later)

    ####################################################################
    # Find
    ####################################################################

    def on_action_find(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.search_entry.grab_focus()

    def on_action_find_next(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.view.find_next()
            def later():
                doc_view.search_entry.grab_focus_without_selecting()
                doc_view.search_entry.set_position(-1)
            GLib.timeout_add(1, later)

    def on_action_find_previous(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.view.find_previous()
            def later():
                doc_view.search_entry.grab_focus_without_selecting()
                doc_view.search_entry.set_position(-1)
            GLib.timeout_add(1, later)

    def on_action_find_clear(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.view.find_cancel()
            doc_view.search_entry.set_text('')
            doc_view.view.grab_focus()

    def search_changed(self, search_entry, doc_view):
        if doc_view is None:
            return
        search_string = search_entry.get_text()
        if not search_string:
            doc_view.find_job = None
            doc_view.view.find_cancel()
        else:
            doc_view.find_job = EvinceView.JobFind.new(
                doc_view.doc,
                doc_view.model.get_page(),
                doc_view.doc.get_n_pages(),
                search_string,
                False)
            doc_view.view.find_search_changed()
            doc_view.view.find_started(doc_view.find_job)
            doc_view.find_job.scheduler_push_job(
                EvinceView.JobPriority.PRIORITY_LOW)

    ####################################################################
    # Duplicate opened file
    ####################################################################

    def on_action_duplicate(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            self.open_file(doc_view.orig_path, doc_view)

    ####################################################################
    # Open in Preview.app (for printing, etc.)
    ####################################################################

    def on_action_preview(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            if doc_view.mime == "image/vnd.djvu":
                app = "DjView"
            else:
                app = "Preview"
            subprocess.call(["open", "-a", app, doc_view.path])

    ####################################################################
    # Print in Preview.app (using applescript)
    ####################################################################

    def on_action_print(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            if doc_view.mime == "image/vnd.djvu":
                app = "DjView"
            else:
                app = "Preview"
            script_code = PRINT_SCRIPT.format(
                app=app, path=doc_view.path)
            script_path = os.path.join(self.tempdir, "print.sctp")
            with open(script_path, "w") as script_file:
                script_file.write(script_code)
            subprocess.call(["osascript", script_path])

    ####################################################################
    # Copy selection to clipboard
    ####################################################################

    def on_action_copy(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.view.copy()

    ####################################################################
    # Zoom actions
    ####################################################################

    def on_action_zoom_in(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.model.set_sizing_mode(EvinceView.SizingMode.FREE)
            doc_view.view.zoom_in()

    def on_action_zoom_out(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.model.set_sizing_mode(EvinceView.SizingMode.FREE)
            doc_view.view.zoom_out()

    def on_action_zoom_100(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.model.set_sizing_mode(EvinceView.SizingMode.FREE)
            doc_view.model.set_scale(1.0)

    def on_action_zoom_fit_width(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.model.set_sizing_mode(EvinceView.SizingMode.FIT_WIDTH)

    def on_action_zoom_fit_page(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            doc_view.model.set_sizing_mode(EvinceView.SizingMode.FIT_PAGE)

    ####################################################################
    # Single page action
    ####################################################################

    def on_action_single_page(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            if doc_view.model.get_continuous():
                doc_view.model.set_continuous(False)
            else:
                doc_view.model.set_continuous(True)

    def keypress_view(self, widget, ev, *args):
        if ev.keyval in [Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_End, Gdk.KEY_Home]:
            doc_view = self.get_current_doc_view()
            if doc_view:
                if not doc_view.model.get_continuous():
                    if ev.keyval == Gdk.KEY_Up:
                        doc_view.view.previous_page()
                    elif ev.keyval == Gdk.KEY_Down:
                        doc_view.view.next_page()
                    elif ev.keyval == Gdk.KEY_End:
                        last = doc_view.doc.get_n_pages()
                        doc_view.model.set_page(last-1)
                    elif ev.keyval == Gdk.KEY_Home:
                        doc_view.model.set_page(0)
                    return True
        return False

    ####################################################################
    # History actions
    ####################################################################

    def on_action_go_next(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            n = doc_view.history_pos
            history = doc_view.history
            if 0 <= n+1 < len(history):
                doc_view.scroll.get_hadjustment().set_value(history[n+1][0])
                doc_view.scroll.get_vadjustment().set_value(history[n+1][1])
                doc_view.history_pos += 1

    def on_action_go_previous(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            n = doc_view.history_pos
            history = doc_view.history
            if 0 <= n-1 < len(history) :
                doc_view.scroll.get_hadjustment().set_value(history[n-1][0])
                doc_view.scroll.get_vadjustment().set_value(history[n-1][1])
                doc_view.history_pos -= 1

    ####################################################################
    # Tab move actions
    ####################################################################

    def on_action_move_tab_up(self, *args):
        cursor, col = self.sidebar_treeview.get_cursor()
        if cursor:
            itr = self.sidebar_model.get_iter(cursor)
            prev_itr = self.sidebar_model.iter_previous(itr)
            if prev_itr:
                self.sidebar_model.move_before(itr, prev_itr)

    def on_action_move_tab_down(self, *args):
        cursor, col = self.sidebar_treeview.get_cursor()
        if cursor:
            itr = self.sidebar_model.get_iter(cursor)
            next_itr = self.sidebar_model.iter_next(itr)
            if next_itr:
                self.sidebar_model.move_after(itr, next_itr)

    ####################################################################
    # BibTeX
    ####################################################################

    def on_action_bibtex(self, *args):
        doc_view = self.get_current_doc_view()
        if doc_view:
            bwin = bib_window.BibWindow(self.app, doc_view.orig_path)
            bwin.show()

    # def load_bibtex(self, bibtex_container, doc_view):
    #     doc_view.bib_fetcher.async_get_bibtex(
    #         self.load_bibtex_cb, bibtex_container, doc_view)

    # def load_bibtex_cb(self, bibtex, original_bibtex, bibtex_container, doc_view):
    #     #bibtex64 = self.load_bibtex64(doc_view)
    #     print(bibtex)
    #     print(original_bibtex)
    #     bibtex64 = (original_bibtex + "\n" + bibtex)
    #     if bibtex64:
    #         doc_view.bibtex_text.get_buffer().set_text(bibtex64)
    #     elif os.path.exists(doc_view.bib_path):
    #         with open(doc_view.bib_path) as bib:
    #             content = bib.read()
    #         doc_view.bibtex_text.get_buffer().set_text(content)
    #     else:
    #         doc_view.bibtex_text.get_buffer().set_text(
    #             "No BibTeX found.\n" + doc_view.bib_path)
    #     # doc_view.bibtex_button.grab_focus()

    # re_bibtex64 = re.compile(r"^%\s*BIBTEX64:(.*)$")
    # def load_bibtex64(self, doc_view):
    #     b64 = None
    #     with open(doc_view.path) as doc_file:
    #         for line in reversed(doc_file.readlines()):
    #             m = self.re_bibtex64.match(line)
    #             if m:
    #                 b64 = m.group(1)
    #                 break
    #     if b64:
    #         return base64.b64decode(b64)



########################################################################
# PulpApplication Class
########################################################################

class PulpApplication(Gtk.Application):

    __gtype_name__ = 'PulpApplication'

    ####################################################################
    # Initialization
    ####################################################################
    
    def __init__(self, *args):
        self.osx_app = GtkosxApplication.Application()
        self.osx_app.connect('NSApplicationOpenFile', self.do_open_mac)
        self._startup_done = False
        super().__init__(*args)

    def do_startup(self, *args):
        Gtk.Application.do_startup(self)
        self.start_server()
        self.setup_css()
        self.setup_menu()
        self.setup_actions()
        self.setup_tempdir()
        self._fds_debug = FdsDebug()
        self._startup_done = True

    def start_server(self):
        self.server_proc = pulp_server.start_pulp_server()

    def setup_css(self):
        css_data = Resource.string("style.css")
        css = Gtk.CssProvider()
        css.load_from_data(css_data)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), 
            css, 
            Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def setup_menu(self):
        menu_file = Resource.filename("ui_menu.xml")
        menu_builder = Gtk.Builder()
        menu_builder.add_from_file(menu_file)
        menu = menu_builder.get_object("app-menu")
        self.set_app_menu(menu)

    def setup_actions(self):
        def add_simple_action(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
        add_simple_action("newwindow", self.on_action_new_window)

    def setup_tempdir(self):
        self.tempdir = tempfile.mkdtemp()

    ####################################################################
    # Quit if no windows are opened
    ####################################################################

    def quit_if_needed(self):
        windows = self.get_windows()
        if not windows:
            self.quit()
    
    ####################################################################
    # Clean exit
    ####################################################################
    
    def do_shutdown(self):
        try:
            shutil.rmtree(self.tempdir)
        except:
            print("Removal of temporary directory failed.")
        Gtk.Application.do_shutdown(self)

    ####################################################################
    # Start application and open files
    ####################################################################
    
    def do_activate(self):
        self.do_open()

    def do_open(self, files=[], hint=None):
        if not self._startup_done:
            self.do_startup()
        window = self.get_windows()
        if window:
            window = window[0]
        else:
            window = PulpWindow(self)
            window.show_all()
        for file in files:
            path = file.get_path()
            window.open_file(path, None, True)
        window.present()

    def do_open_mac(self, osx_app, path, *args):
        file = Gio.File.new_for_path(path)
        self.do_open([file])

    ####################################################################
    # New Window
    ####################################################################

    def on_action_new_window(self, *args):
        new_win = PulpWindow(self)
        new_win.show_all()
        new_win.present()
    

########################################################################
# Main entry point
########################################################################

def main():
    app = PulpApplication()
    app.run()

if __name__ == "__main__":
    main()
