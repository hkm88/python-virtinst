#
# Fullly virtualized guest support
#
# Copyright 2006-2007  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import os
import util
import DistroManager
import logging
import time
import platform

from Guest import Guest
from VirtualDisk import VirtualDisk
from virtinst import _virtinst as _


class FullVirtGuest(Guest):

    def __init__(self, type=None, arch=None, connection=None, hypervisorURI=None, emulator=None, installer=None):
        if not installer:
            installer = DistroManager.DistroInstaller(type = type, os_type = "hvm")
        Guest.__init__(self, type, connection, hypervisorURI, installer)
        self.disknode = "hd"
        self.features = { "acpi": None, "pae": util.is_pae_capable(), "apic": None }
        if arch is None:
            arch = platform.machine()
        self.arch = arch

        self.emulator = emulator
        self.loader = None
        guest = self._caps.guestForOSType(type=self.installer.os_type,
                                          arch=self.arch)
        if (not self.emulator) and guest:
            for dom in guest.domains:
                if dom.hypervisor_type == self.installer.type:
                    self.emulator = dom.emulator
                    self.loader = dom.loader

        # Fall back to default hardcoding
        if self.emulator is None:
            if self.type == "xen":
                if os.uname()[4] in ("x86_64"):
                    self.emulator = "/usr/lib64/xen/bin/qemu-dm"
                else:
                    self.emulator = "/usr/lib/xen/bin/qemu-dm"

        if (not self.loader) and self.type == "xen":
            self.loader = "/usr/lib/xen/boot/hvmloader"

        self._os_type = None
        self._os_variant = None


    def get_os_type(self):
        return self._os_type
    def set_os_type(self, val):
        if type(val) is not str:
            raise ValueError(_("OS type must be a string."))
        val = val.lower()
        if self._OS_TYPES.has_key(val):
            self._os_type = val
            # Invalidate variant, since it may not apply to the new os type
            self._os_variant = None
        else:
            raise ValueError, _("OS type '%s' does not exist in our "
                                "dictionary") % val
    os_type = property(get_os_type, set_os_type)

    def get_os_variant(self):
        return self._os_variant
    def set_os_variant(self, val):
        if type(val) is not str:
            raise ValueError(_("OS variant must be a string."))
        val = val.lower()
        if self._os_type:
            if self._OS_TYPES[self._os_type]["variants"].has_key(val):
                self._os_variant = val
            else:
                raise ValueError, _("OS variant '%(var)s; does not exist in "
                                    "our dictionary for OS type '%(ty)s'" ) % \
                                    {'var' : val, 'ty' : self._os_type}
        else:
            for ostype in self.list_os_types():
                if self._OS_TYPES[ostype]["variants"].has_key(val):
                    logging.debug("Setting os type to '%s' for variant '%s'" %\
                                  (ostype, val))
                    self.os_type = ostype
                    self._os_variant = val
                    return
            raise ValueError, _("Unknown OS variant '%s'" % val)
    os_variant = property(get_os_variant, set_os_variant)

    def os_features(self):
        """Determine the guest features, based on explicit settings in FEATURES
        and the OS_TYPE and OS_VARIANT. FEATURES takes precedence over the OS
        preferences"""
        if self.features is None:
            return None

        # explicitly disabling apic and acpi will override OS_TYPES values
        features = dict(self.features)
        for f in ["acpi", "apic"]:
            val = self._lookup_osdict_key(f)
            features[f] = val
        return features

    def get_os_distro(self):
        return self._lookup_osdict_key("distro")
    os_distro = property(get_os_distro)

    def _get_input_device(self):
        typ = self._lookup_device_param("input", "type")
        bus = self._lookup_device_param("input", "bus")
        return (typ, bus)

    def _get_features_xml(self):
        ret = "<features>\n"
        features = self.os_features()
        if features:
            ret += "    "
            for k in sorted(features.keys()):
                v = features[k]
                if v:
                    ret += "<%s/>" %(k,)
            ret += "\n"
        return ret + "  </features>"

    def _get_osblob(self, install):
        osblob = self.installer._get_osblob(install, hvm = True,
            arch = self.arch, loader = self.loader, conn = self.conn)
        if osblob is None:
            return None

        clockxml = self._get_clock_xml()
        if clockxml is not None:
            return "%s\n  %s\n  %s" % (osblob, self._get_features_xml(), \
                                       clockxml)
        else:
            return "%s\n  %s" % (osblob, self._get_features_xml())

    def _get_clock_xml(self):
        val = self._lookup_osdict_key("clock")
        return """<clock offset="%s"/>""" % val

    def _get_device_xml(self, install=True):
        emu_xml = ""
        if self.emulator is not None:
            emu_xml = "    <emulator>%s</emulator>\n" % self.emulator

        return (emu_xml +
                """    <console type='pty'/>\n""" +
                Guest._get_device_xml(self, install))

    def validate_parms(self):
        Guest.validate_parms(self)

    def _prepare_install(self, meter):
        Guest._prepare_install(self, meter)
        self._installer.prepare(guest = self,
                                meter = meter,
                                distro = self.os_distro)
        if self._installer.install_disk is not None:
            self._install_disks.append(self._installer.install_disk)

    def get_continue_inst(self):
        return self._lookup_osdict_key("continue")

    def continue_install(self, consolecb, meter, wait=True):
        install_xml = self.get_config_xml(disk_boot = True)
        logging.debug("Starting guest from '%s'" % ( install_xml ))
        meter.start(size=None, text="Starting domain...")
        self.domain = self.conn.createLinux(install_xml, 0)
        if self.domain is None:
            raise RuntimeError, _("Unable to start domain for guest, aborting installation!")
        meter.end(0)

        self.connect_console(consolecb, wait)

        # ensure there's time for the domain to finish destroying if the
        # install has finished or the guest crashed
        if consolecb:
            time.sleep(1)

        # This should always work, because it'll lookup a config file
        # for inactive guest, or get the still running install..
        return self.conn.lookupByName(self.name)

    def _get_disk_xml(self, install = True):
        """Get the disk config in the libvirt XML format"""
        ret = ""
        used_targets = []
        for disk in self._install_disks:
            if not disk.bus:
                disk.bus = "ide"
            used_targets.append(disk.generate_target(used_targets))

        for d in self._install_disks:
            saved_path = None
            if d.device == VirtualDisk.DEVICE_CDROM \
               and d.transient and not install:
                # Keep cdrom around, but with no media attached
                # But only if we are a distro that doesn't have a multi
                # stage install (aka not Windows)
                saved_path = d.path
                if not self.get_continue_inst():
                    d.path = None

            if ret:
                ret += "\n"
            ret += d.get_xml_config(d.target)
            if saved_path != None:
                d.path = saved_path

        return ret

    def _set_defaults(self):
        Guest._set_defaults(self)

        disk_bus  = self._lookup_device_param("disk", "bus")
        net_model = self._lookup_device_param("net", "model")

        # Only overwrite params if they weren't already specified
        for net in self._install_nics:
            if net_model and not net.model:
                net.model = net_model
        for disk in self._install_disks:
            if disk_bus and not disk.bus:
                disk.bus = disk_bus
