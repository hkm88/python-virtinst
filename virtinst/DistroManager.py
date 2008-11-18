#
# Convenience module for fetching/creating kernel/initrd files
# or bootable CD images.
#
# Copyright 2006-2007  Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
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

import logging
import os
import util
import Guest
from VirtualDisk import VirtualDisk
from virtinst import _virtinst as _

from ImageFetcher import MountedImageFetcher
from ImageFetcher import FTPImageFetcher
from ImageFetcher import HTTPImageFetcher
from ImageFetcher import DirectImageFetcher

from OSDistro import FedoraDistro
from OSDistro import RHELDistro
from OSDistro import CentOSDistro
from OSDistro import SLDistro
from OSDistro import SuseDistro
from OSDistro import DebianDistro
from OSDistro import UbuntuDistro
from OSDistro import MandrivaDistro
from OSDistro import GenericDistro

def _fetcherForURI(uri, scratchdir=None):
    if uri.startswith("http://"): 
        return HTTPImageFetcher(uri, scratchdir)
    elif uri.startswith("ftp://"):
        return FTPImageFetcher(uri, scratchdir)
    elif uri.startswith("nfs://"):
        return MountedImageFetcher(uri, scratchdir)
    else:
        if os.path.isdir(uri):
            return DirectImageFetcher(uri, scratchdir)
        else:
            return MountedImageFetcher(uri, scratchdir)

def _storeForDistro(fetcher, baseuri, typ, progresscb, arch, distro=None,
                    scratchdir=None):
    stores = []
    logging.debug("Attempting to detect distro:")

    # FIXME: This 'distro ==' doesn't cut it. 'distro' is from our os
    # dictionary, so would look like 'fedora9' or 'rhel5', so this needs
    # to be a bit more intelligent
    if distro == "fedora" or distro is None:
        stores.append(FedoraDistro(baseuri, typ, scratchdir, arch))
    if distro == "rhel" or distro is None:
        stores.append(RHELDistro(baseuri, typ, scratchdir, arch))
    if distro == "centos" or distro is None:
        stores.append(CentOSDistro(baseuri, typ, scratchdir, arch))
    if distro == "sl" or distro is None:
        stores.append(SLDistro(baseuri, typ, scratchdir, arch))
    if distro == "suse" or distro is None:
        stores.append(SuseDistro(baseuri, typ, scratchdir, arch))
    if distro == "debian" or distro is None:
        stores.append(DebianDistro(baseuri, typ, scratchdir, arch))
    if distro == "ubuntu" or distro is None:
        stores.append(UbuntuDistro(baseuri, typ, scratchdir, arch))
    if distro == "mandriva" or distro is None:
        stores.append(MandrivaDistro(baseuri, typ, scratchdir, arch))

    stores.append(GenericDistro(baseuri, typ, scratchdir, arch))

    for store in stores:
        if store.isValidStore(fetcher, progresscb):
            return store

    raise ValueError, _("Could not find an installable distribution at '%s'" % baseuri) 


# Method to fetch a kernel & initrd pair for a particular distro / HV type
def acquireKernel(baseuri, progresscb, scratchdir="/var/tmp", type=None,
                  distro=None, arch=None):
    fetcher = _fetcherForURI(baseuri, scratchdir)
    
    try:
        fetcher.prepareLocation(progresscb)
    except ValueError, e:
        raise ValueError, _("Invalid install location: ") + str(e)

    try:
        store = _storeForDistro(fetcher=fetcher, baseuri=baseuri, typ=type,
                                progresscb=progresscb, distro=distro,
                                scratchdir=scratchdir, arch=arch)
        return store.acquireKernel(fetcher, progresscb)
    finally:
        fetcher.cleanupLocation()

# Method to fetch a bootable ISO image for a particular distro / HV type
def acquireBootDisk(baseuri, progresscb, scratchdir="/var/tmp", type=None,
                    distro=None, arch=None):
    fetcher = _fetcherForURI(baseuri, scratchdir)

    try:
        fetcher.prepareLocation(progresscb)
    except ValueError, e:
        raise ValueError, _("Invalid install location: ") + str(e)

    try:
        store = _storeForDistro(fetcher=fetcher, baseuri=baseuri, typ=type,
                                progresscb=progresscb, distro=distro,
                                scratchdir=scratchdir, arch=arch)
        return store.acquireBootDisk(fetcher, progresscb)
    finally:
        fetcher.cleanupLocation()

class DistroInstaller(Guest.Installer):
    def __init__(self, type = "xen", location = None, boot = None,
                 extraargs = None, os_type = None, conn = None):
        Guest.Installer.__init__(self, type, location, boot, extraargs,
                                 os_type, conn=conn)

        self.install = {
            "kernel" : "",
            "initrd" : "",
            "extraargs" : "",
        }

    def get_location(self):
        return self._location
    def set_location(self, val):
        # 'location' is kind of overloaded: it can be a local file or device
        # path (for a boot.iso), a local directory (for a tree), a
        # tuple of the form (poolname, volname), or an http, ftp, or
        # nfs for an iso or a tree
        if type(val) is tuple and len(val) == 2:
            logging.debug("DistroInstaller location is a (poolname, volname)"
                          " tuple")
        elif os.path.exists(os.path.abspath(val)) \
             and (not self.conn or not util.is_uri_remote(self.conn.getURI())):
            val = os.path.abspath(val)
            logging.debug("DistroInstaller location is a local "
                          "file/path: %s" % val)
        elif val.startswith("nfs://"):
            # Convert RFC compliant NFS      nfs://server/path/to/distro
            # to what mount/anaconda expect  nfs:server:/path/to/distro
            # and carry the latter form around internally
            val = "nfs:" + val[6:]

            # If we need to add the : after the server
            index = val.find("/", 4)
            if index == -1:
                raise ValueError(_("Invalid NFS format: No path specified."))
            if val[index - 1] != ":":
                val = val[:index] + ":" + val[index:] 

        elif (val.startswith("http://") or val.startswith("ftp://") or
              val.startswith("nfs:")):
            logging.debug("DistroInstaller location is a network source.")
        elif self.conn and util.is_storage_capable(self.conn) and \
             util.is_uri_remote(self.conn.getURI()):
            # If conn is specified, pass the path to a VirtualDisk object
            # and see what comes back
            try:
                VirtualDisk(path=val, device=VirtualDisk.DEVICE_CDROM,
                            conn=self.conn)
            except Exception, e:
                raise ValueError(_("Checking installer location failed: %s" %\
                                 str(e)))
        else:
            raise ValueError(_("Install media location must be an NFS, HTTP "
                               "or FTP network install source, or an existing "
                               "local file/device"))

        if os.geteuid() != 0 and val.startswith("nfs:"):
            raise ValueError(_("NFS installations are only supported as root"))

        self._location = val
    location = property(get_location, set_location)

    def _prepare_cdrom(self, guest, distro, meter):
        cdrom = None
        vol_tuple = None
        if type(self.location) is tuple:
            vol_tuple = self.location
        elif self.location.startswith("/"):
            # Huzzah, a local file/device
            cdrom = self.location
        else:
            # Xen needs a boot.iso if its a http://, ftp://, or nfs: url
            arch = os.uname()[4]
            if hasattr(guest, "arch"):
                arch = guest.arch
            cdrom = acquireBootDisk(self.location,
                                    meter,
                                    scratchdir = self.scratchdir,
                                    distro = distro,
                                    arch = arch)
            self._tmpfiles.append(cdrom)

        self._install_disk = VirtualDisk(path=cdrom,
                                         conn=guest.conn,
                                         volName=vol_tuple,
                                         device=VirtualDisk.DEVICE_CDROM,
                                         readOnly=True,
                                         transient=True)

    def _prepare_kernel_and_initrd(self, guest, distro, meter):
        if self.boot is not None:
            # Got a local kernel/initrd already
            self.install["kernel"] = self.boot["kernel"]
            self.install["initrd"] = self.boot["initrd"]
            if not self.extraargs is None:
                self.install["extraargs"] = self.extraargs
        else:
            # Need to fetch the kernel & initrd from a remote site, or
            # out of a loopback mounted disk image/device
            arch = os.uname()[4]
            if hasattr(guest, "arch"):
                arch = guest.arch
            (kernelfn, initrdfn, args) = acquireKernel(self.location,
                                                       meter,
                                                       scratchdir = self.scratchdir,
                                                       type = self.os_type,
                                                       distro = distro,
                                                       arch=arch)
            self.install["kernel"] = kernelfn
            self.install["initrd"] = initrdfn
            if not self.extraargs is None:
                self.install["extraargs"] = self.extraargs + " " + args
            else:
                self.install["extraargs"] = args

            self._tmpfiles.append(kernelfn)
            self._tmpfiles.append(initrdfn)

        # If they're installing off a local file/device, we map it
        # through to a virtual harddisk
        if self.location is not None and self.location.startswith("/") and not os.path.isdir(self.location):
            self._install_disk = VirtualDisk(self.location,
                                             readOnly=True,
                                             transient=True)

    def prepare(self, guest, meter, distro = None):
        self.cleanup()

        self.install = {
            "kernel" : "",
            "initrd" : "",
            "extraargs" : "",
        }

        if self.cdrom:
            if self.location:
                self._prepare_cdrom(guest, distro, meter)
            else:
                # Booting from a cdrom directly allocated to the guest
                pass
        else:
            self._prepare_kernel_and_initrd(guest, distro, meter)

    def _get_osblob(self, install, hvm, arch = None, loader = None,
                     conn = None):
        if install:
            bootdev = "cdrom"
        else:
            bootdev = "hd"

        return self._get_osblob_helper(isinstall=install, ishvm=hvm,
                                       arch=arch, loader=loader, conn=conn,
                                       kernel=self.install, bootdev=bootdev)


class PXEInstaller(Guest.Installer):
    def __init__(self, type = "xen", location = None, boot = None,
                 extraargs = None, os_type = None, conn = None):
        Guest.Installer.__init__(self, type, location, boot, extraargs,
                                 os_type, conn=conn)

    def prepare(self, guest, meter, distro = None):
        pass

    def _get_osblob(self, install, hvm, arch = None, loader = None, conn = None):
        if install:
            bootdev="network"
        else:
            bootdev = "hd"

        return self._get_osblob_helper(isinstall=install, ishvm=hvm,
                                       arch=arch, loader=loader, conn=conn,
                                       kernel=None, bootdev=bootdev)

