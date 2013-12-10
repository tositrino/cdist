#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# 2010-2013 Nico Schottelius (nico-cdist at schottelius.org)
#
# This file is part of cdist.
#
# cdist is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cdist is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with cdist. If not, see <http://www.gnu.org/licenses/>.
#
#

import logging
import os
import shutil
import sys
import time
import pprint

import cdist

import cdist.exec.local
import cdist.exec.remote

from cdist import core
from cdist import dependency


class Config(object):
    """Cdist main class to hold arbitrary data"""

    def __init__(self, local, remote, dry_run=False):

        self.local      = local
        self.remote     = remote
        self.log        = logging.getLogger(self.local.target_host)
        self.dry_run    = dry_run

        self.explorer = core.Explorer(self.local.target_host, self.local, self.remote)
        self.manifest = core.Manifest(self.local.target_host, self.local)
        self.code     = core.Code(self.local.target_host, self.local, self.remote)
        self.dpm = dependency.DependencyManager(os.path.join(self.local.base_path, 'dependency'))

    def _init_files_dirs(self):
        """Prepare files and directories for the run"""
        self.local.create_files_dirs()
        self.remote.create_files_dirs()

    @classmethod
    def commandline(cls, args):
        """Configure remote system"""
        import multiprocessing

        # FIXME: Refactor relict - remove later
        log = logging.getLogger("cdist")
    
        initial_manifest_tempfile = None
        if args.manifest == '-':
            # read initial manifest from stdin
            import tempfile
            try:
                handle, initial_manifest_temp_path = tempfile.mkstemp(prefix='cdist.stdin.')
                with os.fdopen(handle, 'w') as fd:
                    fd.write(sys.stdin.read())
            except (IOError, OSError) as e:
                raise cdist.Error("Creating tempfile for stdin data failed: %s" % e)
    
            args.manifest = initial_manifest_temp_path
            import atexit
            atexit.register(lambda: os.remove(initial_manifest_temp_path))
    
        process = {}
        failed_hosts = []
        time_start = time.time()
    
        for host in args.host:
            if args.parallel:
                log.debug("Creating child process for %s", host)
                process[host] = multiprocessing.Process(target=cls.onehost, args=(host, args, True))
                process[host].start()
            else:
                try:
                    cls.onehost(host, args, parallel=False)
                except cdist.Error as e:
                    failed_hosts.append(host)
    
        # Catch errors in parallel mode when joining
        if args.parallel:
            for host in process.keys():
                log.debug("Joining process %s", host)
                process[host].join()
    
                if not process[host].exitcode == 0:
                    failed_hosts.append(host)
    
        time_end = time.time()
        log.info("Total processing time for %s host(s): %s", len(args.host),
                    (time_end - time_start))
    
        if len(failed_hosts) > 0:
            raise cdist.Error("Failed to configure the following hosts: " + 
                " ".join(failed_hosts))
    
    @classmethod
    def onehost(cls, host, args, parallel):
        """Configure ONE system"""

        log = logging.getLogger(host)
    
        try:
            local = cdist.exec.local.Local(
                target_host=host,
                initial_manifest=args.manifest,
                base_path=args.out_path,
                add_conf_dirs=args.conf_dir)

            remote = cdist.exec.remote.Remote(
                target_host=host,
                remote_exec=args.remote_exec,
                remote_copy=args.remote_copy,
                base_path=args.remote_out_path)
    
            c = cls(local, remote, dry_run=args.dry_run)
            c.run()
    
        except cdist.Error as e:
            log.error(e)
            if parallel:
                # We are running in our own process here, need to sys.exit!
                sys.exit(1)
            else:
                raise
    
        except KeyboardInterrupt:
            # Ignore in parallel mode, we are existing anyway
            if parallel:
                sys.exit(0)
            # Pass back to controlling code in sequential mode
            else:
                raise

    def run(self):
        """Do what is most often done: deploy & cleanup"""
        start_time = time.time()

        self._init_files_dirs()

        self.explorer.run_global_explorers(self.local.global_explorer_out_path)
        self.manifest.run_initial_manifest(self.local.initial_manifest)
        self.iterate_until_finished()

        self.local.save_cache()
        self.log.info("Finished successful run in %s seconds", time.time() - start_time)

    def object_list(self):
        """Short name for object list retrieval"""
        for cdist_object in core.CdistObject.list_objects(self.local.object_path,
                                                         self.local.type_path):
            if cdist_object.cdist_type.is_install:
                self.log.debug("Running in config mode, ignoring install object: {0}".format(cdist_object))
            else:
                yield cdist_object

    def iterate_once(self):
        """
            Iterate over the objects once - helper method for 
            iterate_until_finished
        """
        objects_changed  = False

        for cdist_object in self.object_list():
            deps = self.dpm(cdist_object.name)
            if self.list_unfinished_objects(deps['after']):
                """We cannot do anything for this poor object"""
                continue

            if cdist_object.state == core.CdistObject.STATE_UNDEF:
                """Prepare the virgin object"""
                self.object_prepare(cdist_object)
                objects_changed = True

            deps.reload()
            if self.list_unfinished_objects(deps['auto']):
                """The previous step created objects we depend on - wait for them"""
                continue
        
            if cdist_object.state == core.CdistObject.STATE_PREPARED:
                self.object_run(cdist_object)
                objects_changed = True

        return objects_changed


    def iterate_until_finished(self):
        """
            Go through all objects and solve them
            one after another
        """

        objects_changed = True

        while objects_changed:
            objects_changed = self.iterate_once()

        # Check whether all objects have been finished
        unfinished_objects = self.list_unfinished_objects()

        if unfinished_objects:
            info_string = []

            for cdist_object in unfinished_objects:

                deps = self.dpm(cdist_object.name)
                unresolved_deps = {
                    'require': [obj.name for obj in self.list_unfinished_objects(deps['after'])],
                    'auto': [obj.name for obj in self.list_unfinished_objects(deps['auto'])],
                }
                info_string.append("{0}: {1}".format(cdist_object.name, pprint.pformat(unresolved_deps)))

            raise cdist.UnresolvableRequirementsError("The requirements of the following objects could not be resolved:\n%s" %
                ("\n".join(info_string)))

    def object_from_name(self, object_name):
        base_path = self.local.object_path
        type_path = self.local.type_path
        type_name, object_id = core.CdistObject.split_name(object_name)
        cdist_type = core.CdistType(type_path, type_name)
        return core.CdistObject(cdist_type, base_path, object_id=object_id)

    def list_unfinished_objects(self, object_list=None):
        """Return a list of objects that are not yet finished."""

        unfinished = []
        if object_list is None:
            object_list = self.object_list()
        for object_or_name in object_list:
            if isinstance(object_or_name, core.CdistObject):
                cdist_object = object_or_name
            else:
                cdist_object = self.object_from_name(object_or_name)
            if cdist_object.state != cdist_object.STATE_DONE:
                unfinished.append(cdist_object)
        return unfinished

    def object_prepare(self, cdist_object):
        """Prepare object: Run type explorer + manifest"""
        self.log.info("Running manifest and explorers for " + cdist_object.name)
        self.explorer.run_type_explorers(cdist_object)
        self.manifest.run_type_manifest(cdist_object)
        cdist_object.state = core.CdistObject.STATE_PREPARED

    def object_run(self, cdist_object):
        """Run gencode and code for an object"""

        self.log.debug("Trying to run object %s" % (cdist_object.name))
        if cdist_object.state == core.CdistObject.STATE_DONE:
            raise cdist.Error("Attempting to run an already finished object: %s", cdist_object)

        cdist_type = cdist_object.cdist_type

        # Generate
        self.log.info("Generating code for %s" % (cdist_object.name))
        cdist_object.code_local = self.code.run_gencode_local(cdist_object)
        cdist_object.code_remote = self.code.run_gencode_remote(cdist_object)
        if cdist_object.code_local or cdist_object.code_remote:
            cdist_object.changed = True

        # Execute
        if not self.dry_run:
            if cdist_object.code_local or cdist_object.code_remote:
                self.log.info("Executing code for %s" % (cdist_object.name))
            if cdist_object.code_local:
                self.code.run_code_local(cdist_object)
            if cdist_object.code_remote:
                self.code.transfer_code_remote(cdist_object)
                self.code.run_code_remote(cdist_object)
        else:
            self.log.info("Skipping code execution due to DRY RUN")


        # Mark this object as done
        self.log.debug("Finishing run of " + cdist_object.name)
        cdist_object.state = core.CdistObject.STATE_DONE
