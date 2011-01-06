#!/usr/bin/env python
# vim: sts=4 sw=4 et
# GladeVcp actions
#
# Copyright (c) 2010  Pavel Shramov <shramov@mexmat.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

import gobject
import gtk
import os
import time
import re, string

from hal_widgets import _HalWidgetBase
import emc
from hal_glib import GStat

_ = lambda x: x

class _EMCStaticHolder:
    def __init__(self):
        # Delay init...
        self.emc = None
        self.stat = None
        self.gstat = None

    def get(self):
        if not self.emc:
            self.emc = emc.command()
        if not self.gstat:
            self.gstat = GStat()
        return self.emc, self.gstat.stat, self.gstat

class _EMCStatic:
    holder = _EMCStaticHolder()
    def get(self):
        return self.holder.get()

class _EMC_ActionBase(_HalWidgetBase):
    _gproperties = {'name': (gobject.TYPE_STRING, 'Name', 'Action name', "",
                             gobject.PARAM_READWRITE|gobject.PARAM_CONSTRUCT)
                   }

    emc_static = _EMCStatic()

    def _hal_init(self):
        self.emc, self.stat, self.gstat = self.emc_static.get()
        self._stop_emission = False

    def machine_on(self):
        self.stat.poll()
        return self.stat.task_state > emc.STATE_OFF

    def safe_handler(self, f):
        def _f(self, *a, **kw):
            if self._stop_emission:
                return
            return f(self, *a, **kw)
        return _f

    def do_get_property(self, property):
        name = property.name.replace('-', '_')

        if name == 'name':
            return self.get_name()
        elif name == 'label':
            return self.get_label()
        elif name == 'tooltip':
            return self.get_tooltip()
        elif name == 'stock_id':
            return self.get_stock_id()
        else:
            raise AttributeError("Unknown property: %s" % property.name)

    def do_set_property(self, property, value):
        name = property.name.replace('-', '_')

        if name == 'name':
            if value:
                self.set_name(value)
        elif name == 'label':
            self.set_label(value)
        elif name == 'tooltip':
            self.set_tooltip(value)
        elif name == 'stock_id':
            self.set_stock_id(value)
        else:
            raise AttributeError("Unknown property: %s" % property.name)
        return True

class _EMC_Action(gtk.Action, _EMC_ActionBase):
    __gproperties__ = _EMC_ActionBase._gproperties
    def __init__(self, name=None):
        gtk.Action.__init__(self, None, None, None, None)
        self._stop_emission = True
        self.connect('activate', self.safe_handler(self.on_activate))

    def on_activate(self, w):
        return True

class _EMC_ToggleAction(gtk.ToggleAction, _EMC_ActionBase):
    __gproperties__ = _EMC_ActionBase._gproperties
    def __init__(self, name=None):
        gtk.Action.__init__(self, None, None, None, None)
        self._stop_emission = False
        self.connect('toggled', self.safe_handler(self.on_toggled))

    def set_active_safe(self, active):
        self._stop_emission = True
        self.set_active(active)
        self._stop_emission = False

    def on_toggled(self, w):
        return True

class EMC_Stat(GStat, _EMC_ActionBase):
    __gtype_name__ = 'EMC_Stat'
    def __init__(self):
        stat = self.emc_static.get()[2]
        GStat.__init__(self, stat)

    def _hal_init(self):
        pass

def _action(klass, f, *a, **kw):
    class _C(_EMC_Action):
        __gtype_name__ = klass
        def on_activate(self, w):
            print klass
            f(self, *a, **kw)
    return _C

EMC_Action_ESTOP = _action('EMC_Action_ESTOP', lambda s: s.emc.state(emc.STATE_ESTOP))
EMC_Action_ESTOP_RESET = _action('EMC_Action_ESTOP_RESET', lambda s: s.emc.state(emc.STATE_ESTOP_RESET))
EMC_Action_ON    = _action('EMC_Action_ON', lambda s: s.emc.state(emc.STATE_ON))
EMC_Action_OFF   = _action('EMC_Action_OFF', lambda s: s.emc.state(emc.STATE_OFF))

class EMC_ToggleAction_ESTOP(_EMC_ToggleAction):
    __gtype_name__ = 'EMC_ToggleAction_ESTOP'
    def _hal_init(self):
        _EMC_ToggleAction._hal_init(self)

        self.set_active_safe(True)

        self.gstat.connect('state-estop', lambda w: self.set_active_safe(True))
        self.gstat.connect('state-estop-reset', lambda w: self.set_active_safe(False))

    def on_toggled(self, w):
        if self.get_active():
            print 'Issuing ESTOP'
            self.emc.state(emc.STATE_ESTOP)
        else:
            print 'Issuing ESTOP RESET'
            self.emc.state(emc.STATE_ESTOP_RESET)

class EMC_ToggleAction_Power(_EMC_ToggleAction):
    __gtype_name__ = 'EMC_ToggleAction_Power'
    def _hal_init(self):
        _EMC_ToggleAction._hal_init(self)

        self.set_active_safe(False)
        self.set_sensitive(False)

        self.gstat.connect('state-on',  lambda w: self.set_active_safe(True))
        self.gstat.connect('state-off', lambda w: self.set_active_safe(False))
        self.gstat.connect('state-estop', lambda w: self.set_sensitive(False))
        self.gstat.connect('state-estop-reset', lambda w: self.set_sensitive(True))

    def on_toggled(self, w):
        if self.get_active():
            print 'Issuing ON'
            self.emc.state(emc.STATE_ON)
        else:
            print 'Issuing OFF'
            self.emc.state(emc.STATE_OFF)

def running(s, do_poll=True):
    if do_poll: s.poll()
    return s.task_mode == emc.MODE_AUTO and s.interp_state != emc.INTERP_IDLE

def ensure_mode(s, c, *modes):
    s.poll()
    if not modes: return False
    if s.task_mode in modes: return True
    if running(s, do_poll=False): return False
    c.mode(modes[0])
    c.wait_complete()
    return True

class EMC_Action_Run(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Run'
    def on_activate(self, w):
        program_start_line = 0
        ensure_mode(self.stat, self.emc, emc.MODE_AUTO)
        self.emc.auto(emc.AUTO_RUN, program_start_line)

class EMC_Action_Step(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Step'
    def _hal_init(self):
        _EMC_Action._hal_init(self)

        self.gstat.connect('state-off', lambda w: self.set_sensitive(False))
        self.gstat.connect('state-estop', lambda w: self.set_sensitive(False))
        self.gstat.connect('interp-idle', lambda w: self.set_sensitive(self.machine_on()))

    def on_activate(self, w):
        ensure_mode(self.stat, self.emc, emc.MODE_AUTO)
        self.emc.auto(emc.AUTO_STEP)

class EMC_Action_Pause(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Pause'
    def on_activate(self, w):
        self.stat.poll()
        if self.stat.task_mode != emc.MODE_AUTO or\
                self.stat.interp_state not in (emc.INTERP_READING, emc.INTERP_WAITING):
            return
        ensure_mode(self.stat, self.emc, emc.MODE_AUTO)
        self.emc.auto(emc.AUTO_PAUSE)

class EMC_Action_Resume(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Resume'
    def on_activate(self, w):
        print "RESUME"
        self.stat.poll()
        if not self.stat.paused:
            return
        if self.stat.task_mode not in (emc.MODE_AUTO, emc.MODE_MDI):
            return
        ensure_mode(self.stat, self.emc, emc.MODE_AUTO, emc.MODE_MDI)
        self.emc.auto(emc.AUTO_RESUME)

class EMC_Action_Stop(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Stop'
    def on_activate(self, w):
        self.emc.abort()
        self.emc.wait_complete()

class EMC_ToggleAction_Run(_EMC_ToggleAction, EMC_Action_Run):
    __gtype_name__ = 'EMC_ToggleAction_Run'
    def _hal_init(self):
        _EMC_ToggleAction._hal_init(self)

        self.set_active_safe(False)
        self.set_sensitive(False)

        self.gstat.connect('state-off', lambda w: self.set_sensitive(False))
        self.gstat.connect('state-estop', lambda w: self.set_sensitive(False))

        self.gstat.connect('interp-idle', lambda w: self.set_sensitive(self.machine_on()))
        self.gstat.connect('interp-idle', lambda w: self.set_active_safe(False))
        self.gstat.connect('interp-run', lambda w: self.set_sensitive(False))
        self.gstat.connect('interp-run', lambda w: self.set_active_safe(True))

    def on_toggled(self, w):
        if self.get_active():
            return self.on_activate(w)

class EMC_ToggleAction_Stop(_EMC_ToggleAction, EMC_Action_Stop):
    __gtype_name__ = "EMC_ToggleAction_Stop"
    def _hal_init(self):
        _EMC_ToggleAction._hal_init(self)

        self.set_active_safe(True)
        self.set_sensitive(False)

        self.gstat.connect('state-off', lambda w: self.set_sensitive(False))
        self.gstat.connect('state-estop', lambda w: self.set_sensitive(False))

        self.gstat.connect('interp-idle', lambda w: self.set_sensitive(False))
        self.gstat.connect('interp-idle', lambda w: self.set_active_safe(True))
        self.gstat.connect('interp-run', lambda w: self.set_sensitive(self.machine_on()))
        self.gstat.connect('interp-run', lambda w: self.set_active_safe(False))

    def on_toggled(self, w):
        if self.get_active():
            return self.on_activate(w)

class EMC_ToggleAction_Pause(_EMC_ToggleAction, EMC_Action_Pause):
    __gtype_name__ = "EMC_ToggleAction_Pause"
    def _hal_init(self):
        _EMC_ToggleAction._hal_init(self)

        self.resume = EMC_Action_Resume()
        self.resume._hal_init()

        self.set_active_safe(True)
        self.set_sensitive(False)

        self.gstat.connect('state-off', lambda w: self.set_sensitive(False))
        self.gstat.connect('state-estop', lambda w: self.set_sensitive(False))

        self.gstat.connect('interp-idle', lambda w: self.set_sensitive(False))
        self.gstat.connect('interp-idle', lambda w: self.set_active_safe(False))
        self.gstat.connect('interp-run', lambda w: self.set_sensitive(self.machine_on()))
        self.gstat.connect('interp-run', lambda w: self.set_active_safe(False))
        self.gstat.connect('interp-paused', lambda w: self.set_active_safe(True))

    def on_toggled(self, w):
        if self.get_active():
            return self.on_activate(w)
        else:
            return self.resume.on_activate(self.resume)

class HalTemplate(string.Template):
    idpattern = '[_a-z][-._a-z0-9]*'

class FloatComp:
    def __init__(self, comp):
        self.comp = comp
    def __getitem__(self, k):
        return float(self.comp[k])

class EMC_Action_MDI(_EMC_Action):
    __gtype_name__ = 'EMC_Action_MDI'
    command = gobject.property(type=str, default='', nick='MDI Command')

    def _hal_init(self):
        _EMC_Action._hal_init(self)

        self.gstat.connect('state-off', lambda w: self.set_sensitive(False))
        self.gstat.connect('state-estop', lambda w: self.set_sensitive(False))
        self.gstat.connect('interp-idle', lambda w: self.set_sensitive(self.machine_on()))
        self.gstat.connect('interp-run', lambda w: self.set_sensitive(False))

    def on_activate(self, w):
        ensure_mode(self.stat, self.emc, emc.MODE_MDI)
        template = HalTemplate(self.command)
        cmd = template.substitute(FloatComp(self.hal))
        self.emc.mdi(cmd)

class EMC_ToggleAction_MDI(_EMC_ToggleAction, EMC_Action_MDI):
    __gtype_name__ = 'EMC_ToggleAction_MDI'
    __gsignals__ = {
        'mdi-command-start': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, ()),
        'mdi-command-stop':  (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, ()),
    }
    command = gobject.property(type=str, default='', nick='MDI Command')

    def _hal_init(self):
        _EMC_ToggleAction._hal_init(self)
        EMC_Action_MDI._hal_init(self)

    def on_toggled(self, w):
        if not self.get_active():
            return
        self.set_sensitive(False)
        self.emit('mdi-command-start')
        self.on_activate(w)
        gobject.timeout_add(100, self.wait_complete)

    def wait_complete(self):
        if self.emc.wait_complete(0) in [-1, emc.RCS_EXEC]:
            return True
        self.emit('mdi-command-stop')
        self.set_active_safe(False)
        self.set_sensitive(self.machine_on())
        return False

class EMC_Action_Home(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Unhome'
    axis = gobject.property(type=int, default=-1, nick='Axis to unhome. -1 to unhome all')
    def on_activate(self, w):
        ensure_mode(self.stat, self.emc, emc.MODE_MANUAL)
        self.emc.unhome(self.axis)

def prompt_areyousure(type, message, secondary=None):
    dialog = gtk.MessageDialog(None, 0, type, gtk.BUTTONS_YES_NO, message)
    if secondary:
        dialog.format_secondary_text(secondary)
    r = dialog.run()
    dialog.destroy()
    return r == gtk.RESPONSE_YES

class EMC_Action_Home(_EMC_Action):
    __gtype_name__ = 'EMC_Action_Home'
    axis = gobject.property(type=int, default=-1, nick='Axis to home. -1 to home all')
    confirm_homed = gobject.property(type=bool, default=False, nick='Confirm rehoming',
                                     blurb='Ask user if axis is already homed')
    def homed(self):
        if self.axis != -1:
            return self.stat.homed[self.axis]
        for i,h in enumerate(self.stat.homed):
            if h and self.stat.axis_mask & (1<<i):
                return True

    def on_activate(self, w):
        #if not manual_ok(): return
        ensure_mode(self.stat, self.emc, emc.MODE_MANUAL)
        if self.confirm_homed and self.homed():
            if not prompt_areyousure(gtk.MESSAGE_WARNING,
                            _("Axis is already homed, are you sure you want to re-home?")):
                return
        self.emc.home(self.axis)