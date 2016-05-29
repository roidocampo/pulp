#!/usr/bin/env python3

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Pango

from . import bib_fetcher


class BibWindow(Gtk.ApplicationWindow):

    def __init__(self, app, path):
        super().__init__(application = app)
        self.app = app
        self.path = path
        self.init_ui()
        self.init_actions()

    def init_actions(self):
        def add_simple_action(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
        add_simple_action("close", self.on_action_close)
        # add_simple_action("copy", self.on_action_copy)
        add_simple_action("quit", self.on_action_close)

    def init_ui(self):
        # head = Gtk.HeaderBar()
        vbox = Gtk.VBox()
        pvbox = Gtk.VBox()
        ovbox = Gtk.VBox()
        hbox = Gtk.HBox()
        personal = Gtk.TextView()
        online = Gtk.TextView()
        plabel = Gtk.Label("Personal BibTeX data.")
        olabel = Gtk.Label("BibTeX fetched online.")
        pframe_outer = Gtk.Frame()
        oframe_outer = Gtk.Frame()
        pframe_inner = Gtk.Frame()
        oframe_inner = Gtk.Frame()
        pscroll = Gtk.ScrolledWindow()
        oscroll = Gtk.ScrolledWindow()
        paction_bar = Gtk.Frame()
        paction_bar_inner = Gtk.HBox()
        save_button = Gtk.Button("Save")
        cancel_button = Gtk.Button("Cancel")

        self.add(vbox)
        # vbox.pack_start(head, False, True, 0)
        vbox.pack_start(hbox, True, True, 0)
        hbox.pack_start(pframe_outer, False, False, 0)
        hbox.pack_start(oframe_outer, True, True, 0)
        pframe_outer.add(pvbox)
        pvbox.pack_start(plabel, False, True, 0)
        pvbox.pack_start(pframe_inner, True, True, 0)
        pvbox.pack_start(paction_bar, False, False, 0)
        pframe_inner.add(pscroll)
        pscroll.add(personal)
        oframe_outer.add(ovbox)
        ovbox.pack_start(olabel, False, True, 0)
        ovbox.pack_start(oframe_inner, True, True, 0)
        oframe_inner.add(oscroll)
        oscroll.add(online)

        paction_bar.add(paction_bar_inner)
        paction_bar_inner.pack_start(save_button, False, True, 0)
        paction_bar_inner.pack_start(cancel_button, False, True, 10)

        self.set_title("Pulp - BibTeX - " + self.path)
        self.move(40,50)
        self.resize(1350, 820)
        pframe_outer.set_size_request(500,-1)

        personal.override_font( Pango.font_description_from_string('Menlo Regular 13'))
        online.override_font( Pango.font_description_from_string('Menlo Regular 13'))

        personal.set_editable(False)
        online.set_editable(False)

        self.get_style_context().add_class("bib-window")
        pframe_outer.get_style_context().add_class("personal")
        oframe_outer.get_style_context().add_class("online")
        pframe_outer.get_style_context().add_class("outer-frame")
        oframe_outer.get_style_context().add_class("outer-frame")
        paction_bar.get_style_context().add_class("save-bar")
        plabel.get_style_context().add_class("title-label")
        olabel.get_style_context().add_class("title-label")

        online.get_buffer().set_text("Loading BibTeX...")
        personal.get_buffer().set_text("Loading BibTeX...")
        personal.get_buffer().set_modified(False)

        self.personal = personal
        self.online = online
        self.paction_bar = paction_bar
        self.personal_modified = False

        self.show_all()
        self.paction_bar.hide()
        self.hide()

        fetcher = bib_fetcher.ThreadedBibFetcher(self.path)
        fetcher.async_get_bibtex(self.load_cache, self.load_bib)
        self.fetcher = fetcher

        personal.get_buffer().connect("modified-changed", self.mod_changed)
        save_button.connect("clicked", self.save_pbib)
        cancel_button.connect("clicked", self.reset_pbib)

        # self.connect('key-press-event', self.keypress)
        # self.connect('delete-event', self.on_close)

    def load_cache(self, cache_bib, personal_bib):
        if cache_bib:
            self.online.get_buffer().set_text("# cached BibTeX\n\n" + cache_bib)
        self.personal.set_editable(True)
        self.personal_bib = personal_bib
        self.personal_modified = False
        if personal_bib:
            self.personal.get_buffer().set_text(personal_bib)
        else:
            self.personal.get_buffer().set_text("")
        self.personal.get_buffer().set_modified(False)

    def load_bib(self, bibtex):
        self.online.get_buffer().set_text(bibtex)

    def mod_changed(self, pbuffer):
        if pbuffer.get_modified():
            self.personal_modified = True
            self.paction_bar.show()
            self.personal.get_style_context().add_class("modified")
        else:
            self.personal_modified = False
            self.paction_bar.hide()
            self.personal.get_style_context().remove_class("modified")

    def save_pbib(self, button):
        new_pbib = self.personal.get_buffer().get_property("text")
        self.fetcher.save_personal_bib(new_pbib)
        self.personal_bib = new_pbib
        self.personal.get_buffer().set_modified(False)

    def reset_pbib(self, button):
        self.personal.get_buffer().set_text(self.personal_bib)
        self.personal.get_buffer().set_modified(False)

    def on_action_close(self, *args):
        if self.personal_modified:
            pass
        else:
            self.close()

    def on_action_copy(self, *args):
        pass

    # def on_close(self, widget, event):
    #     if self.personal_modified:
    #         return True
    #     else:
    #         return False

    # def keypress(self, widget, event):
    #     keyname = Gdk.keyval_name(event.keyval)
    #     ctrl = event.state & (
    #             Gdk.ModifierType.CONTROL_MASK
    #             | Gdk.ModifierType.MOD2_MASK)

    #     if (ctrl and (keyname == 'q' or keyname == 'w')) or keyname == 'Escape':
    #         if not self.personal_modified:
    #             self.close()

    #     elif ctrl and keyname == 's':
    #         if self.personal_modified:
    #             self.save_pbib(None)

    #     elif ctrl and keyname == 'r':
    #         if self.personal_modified:
    #             self.reset_pbib(None)

