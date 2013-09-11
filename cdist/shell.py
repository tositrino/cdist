# -*- coding: utf-8 -*-
#
# 2013 Nico Schottelius (nico-cdist at schottelius.org)
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
import subprocess

# initialise cdist
import cdist.exec.local


import cdist.config

log = logging.getLogger(__name__)

class Shell(object):
    
    def __init__(self, shell=None):

        self.shell = shell

        self.target_host = "cdist-shell-no-target-host"
        self.local = cdist.exec.local.Local(
            target_host=self.target_host)

    def _init_shell(self):
        """Select shell to execute, if not specified by user"""

        if not self.shell:
            if 'SHELL' in os.environ:
                self.shell = os.environ['SHELL']
            else:
                self.shell = "/bin/sh"

    def _init_files_dirs(self):
        self.local.create_files_dirs()

    def _init_environment(self):
        self.env = os.environ.copy()
        additional_env = { 
            'PATH': "%s:%s" % (self.local.bin_path, os.environ['PATH']),
            '__cdist_type_base_path': self.local.type_path, # for use in type emulator
            '__cdist_manifest': "cdist shell",
            '__global': self.local.base_path,
            '__target_host': self.target_host,
            '__manifest': self.local.manifest_path,
            '__explorer': self.local.global_explorer_path,
        }

        self.env.update(additional_env)

    def run(self):
        self._init_shell()
        self._init_files_dirs()
        self._init_environment()

        log.info("Starting shell...")
        self.local.run([self.shell], self.env)
        log.info("Finished shell.")

    @classmethod
    def commandline(cls, args):
        shell = cls(args.shell)
        shell.run()
