#!/usr/bin/env python
# encoding: utf-8
#
# pmatic - A simple API to to the Homematic CCU2
# Copyright (C) 2016 Lars Michelsen <lm@larsmichelsen.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

# Add Python 3.x behaviour to 2.7
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import re
import time

import pmatic.utils as utils
from pmatic.exceptions import PMUserError, PMException

try:
    from simpletr64.actions.lan import Lan as SimpleTR64Lan
except ImportError as e:
    if "simpletr64" in str(e):
        SimpleTR64Lan = None
    else:
        raise


class Residents(utils.LogMixin):
    """This class is meant to manage your residents and the presence of them."""
    def __init__(self):
        super(Residents, self).__init__()
        self.residents = []


    def from_config(self, cfg):
        """Build the Residents object, residents and devices from a persisted
        configuration dictionary."""
        self.clear()
        for resident_cfg in cfg.get("residents", []):
            p = Resident(self)
            p.from_config(resident_cfg)
            self.add(p)


    def to_config(self):
        """Returns a dictionary representing the whole residents configuration.
        This dictionary can be saved somewhere, for example in a file, loaded
        afterwards and handed over to :meth:`from_config` to reconstruct the
        current Residents object."""
        return {
            "residents": [ p.to_config() for p in self.residents ],
        }


    @property
    def enabled(self):
        """Is set to ``True`` when the presence detection shal be enabled."""
        return bool(self.residents)


    def update(self):
        """Call this to update the presence information of all configured residents
        and their devices. This normally calls the presence plugins to update the
        presence information from the connected data source."""
        self.logger.debug("Updating presence information")
        for resident in self.residents:
            resident.update_presence()


    def add(self, r):
        """Add a :class:`Resident` object to the presence detection."""
        num = len(self.residents)
        r.id = num
        self.residents.append(r)


    def exists(self, resident_id):
        """Returns ``True`` when a resident with the given id exists.
        Otherwise ``False`` is returned."""
        return resident_id < len(self.residents)


    def get(self, resident_id):
        """Returns the :class:`Resident` matching the given ``resident_id``. Raises an
        ``IndexError`` when this resident does not exist."""
        return self.residents[resident_id]


    def get_by_name(self, resident_name):
        """Returns the first :class:`Resident` matching the given ``resident_name``. Returns
        ``None`` when there is no resident with this name."""
        for resident in self.residents:
            if resident.name == resident_name:
                return resident
        return None


    def remove(self, resident_id):
        """Removes the resident with the given ``resident_id`` from the Residents. Tolerates non
        existing resident ids."""
        try:
            self.residents.pop(resident_id)
        except IndexError:
            pass


    def clear(self):
        """Resets the Persence object to it's initial state."""
        self.residents = []



class Resident(utils.LogMixin):
    def __init__(self, presence):
        super(Resident, self).__init__()
        self._presence = presence
        self.id        = None
        self.devices   = []

        self.name      = "Mr. X"
        self.email     = ""
        self.mobile    = ""
        self.pushover_token = ""

        self._presence_updated = None
        self._presence_changed = None
        self._present          = False


    @property
    def last_updated(self):
        """Is set to the unix timestamp of the last update or ``None`` when not updated yet."""
        return self._presence_updated


    @property
    def last_changed(self):
        """Is set to the unix timestamp of the last presence
        change or ``None`` when not updated yet."""
        return self._presence_changed


    def from_config(self, cfg):
        self.name    = cfg["name"]
        self.email   = cfg["email"]
        self.mobile  = cfg["mobile"]
        self.pushover_token = cfg["pushover_token"]

        self.devices = []
        for device_cfg in cfg.get("devices", []):
            cls = PersonalDevice.get(device_cfg["type_name"])
            if not cls:
                raise PMUserError("Failed to load personal device type: %s" %
                                                            device_cfg["type_name"])

            device = cls()
            device.from_config(device_cfg)
            self.add_device(device)


    def to_config(self):
        return {
            "name"           : self.name,
            "email"          : self.email,
            "mobile"         : self.mobile,
            "pushover_token" : self.pushover_token,
            "devices" : [ d.to_config() for d in self.devices ],
        }


    @property
    def present(self):
        """Is ``True`` when the user is present and ``False`` when not."""
        return self._present


    def add_device(self, device):
        """Adds a :class:`PersonalDevice` object to the resident. Please note that
        you need to use a specific class inherited from :class:`PersonalDevice`,
        for example the :class:`PersonalDeviceFritzBoxHost` class."""
        self.devices.append(device)


    def update_presence(self):
        """Updates the presence of this resident. When at least one device is active,
        the resident is treated to be present."""
        if not self.devices:
            self.logger.debug("Has no devices associated. Not updating the presence.")
            return

        new_value = False
        for device in self.devices:
            if device.active:
                new_value = True
                break

        self._set_presence(new_value)


    def _set_presence(self, new_value):
        """Internal helper for setting the presence state"""
        old_value = self._present

        now = time.time()
        self._presence_updated = now

        self._present = new_value
        if new_value != old_value:
            self._presence_changed = now


    def clear_devices(self):
        """Resets the device list to it's initial state."""
        self.devices = []



class PersonalDevice(object):
    type_name  = ""
    type_title = ""

    @classmethod
    def types(cls):
        """Returns a list of all available specific PersonalDevice classes"""
        return cls.__subclasses__()


    @classmethod
    def get(cls, type_name):
        """Returns the subclass of PersonalDevice which matches the given :attr:`type_name`
        or ``None`` if there is no match."""
        for subclass in cls.__subclasses__():
            if subclass.type_name == type_name:
                return subclass
        return None


    def __init__(self):
        super(PersonalDevice, self).__init__()
        self._name   = "Unspecific device"
        self._active = False


    def from_config(self, cfg):
        for key, val in cfg.items():
            setattr(self, "_" + key, val)


    def to_config(self):
        return {
            "type_name": self.type_name,
        }


    @property
    def name(self):
        """Provides the name of this device."""
        return self._name


    @property
    def active(self):
        """Whether or not this device is currently active."""
        return self._active



class PersonalDeviceFritzBoxHost(PersonalDevice):
    type_name = "fritz_box_host"
    type_title = "fritz!Box Host"

    # Class wide connection handling (not per object)
    connection = None
    _address   = "fritz.box"
    _protocol  = "http"
    _port      = 49000
    _user      = ""
    _password  = ""

    @classmethod
    def configure(cls, address=None, protocol=None, port=None, user=None, password=None):
        if address != None:
            cls._address = address
        if protocol != None:
            cls._protocol = protocol
        if port != None:
            cls._port = port
        if user != None:
            cls._user = user
        if password != None:
            cls._password = password


    @classmethod
    def _connect(cls):
        if SimpleTR64Lan == None:
            raise PMException("Could not import the required \"simpletr64.actions.lan.Lan\".")

        if cls.connection == None:
            cls.connection = SimpleTR64Lan(hostname=cls._address,
                                           port=cls._port,
                                           protocol=cls._protocol)
            cls.connection.setupTR64Device("fritz.box")
            cls.connection.username = cls._user
            cls.connection.password = cls._password


    def __init__(self):
        super(PersonalDeviceFritzBoxHost, self).__init__()
        self._name       = "fritz!Box Device"
        self._ip_address = None
        self._mac        = None


    @property
    def mac(self):
        """Provides the MAC address of this device."""
        return self._mac


    @mac.setter
    def mac(self, mac):
        if not re.match("^([0-9A-Fa-f]{2}:){5}([0-9A-Fa-f]{2})$", mac):
            raise PMUserError("The given MAC address ins not valid.")
        self._mac = mac


    def to_config(self):
        cfg = super(PersonalDeviceFritzBoxHost, self).to_config()
        cfg["mac"] = self.mac
        return cfg


    def _update_host_info(self):
        PersonalDeviceFritzBoxHost._connect()
        try:
            result = PersonalDeviceFritzBoxHost.connection.getHostDetailsByMACAddress(self._mac)
        except ValueError as e:
            # Is raised when no device with this mac can be found
            if "NoSuchEntryInArray" in str(e):
                return
            else:
                raise

        self._ip_address = result.ipaddress
        self._name       = result.hostname
        self._active     = result.active