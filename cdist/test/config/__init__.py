# -*- coding: utf-8 -*-
#
# 2010-2011 Steven Armstrong (steven-cdist at armstrong.cc)
# 2012-2013 Nico Schottelius (nico-cdist at schottelius.org)
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

import os
import shutil

from cdist import test
from cdist import core

import cdist
import cdist.config
import cdist.core.cdist_type
import cdist.core.cdist_object

import os.path as op
my_dir = op.abspath(op.dirname(__file__))
fixtures = op.join(my_dir, 'fixtures')
object_base_path = op.join(fixtures, 'object')
type_base_path = op.join(fixtures, 'type')
add_conf_dir = op.join(fixtures, 'conf')

class ConfigRunTestCase(test.CdistTestCase):

    def setUp(self):

        # Change env for context
        self.orig_environ = os.environ
        os.environ = os.environ.copy()
        self.temp_dir = self.mkdtemp()

        self.local_dir = os.path.join(self.temp_dir, "local")
        os.mkdir(self.local_dir)
        self.local = cdist.exec.local.Local(
            target_host=self.target_host,
            base_path=self.local_dir)

        self.remote_dir = os.path.join(self.temp_dir, "remote")
        os.mkdir(self.remote_dir)
        self.remote = cdist.exec.remote.Remote(
            target_host=self.target_host,
            remote_copy=self.remote_copy,
            remote_exec=self.remote_exec,
            base_path=self.remote_dir)

        self.local.object_path  = object_base_path
        self.local.type_path    = type_base_path

        self.config = cdist.config.Config(self.local, self.remote)

        self.objects = list(core.CdistObject.list_objects(object_base_path, type_base_path))
        self.object_index = dict((o.name, o) for o in self.objects)
        self.object_names = [o.name for o in self.objects]

    def tearDown(self):
        for o in self.objects:
            o.state = ""

        os.environ = self.orig_environ
        shutil.rmtree(self.temp_dir)

    def test_dependency_resolution(self):
        first   = self.object_index['__first/man']
        second  = self.object_index['__second/on-the']
        third   = self.object_index['__third/moon']

        self.context.dpm.after(first.name, second.name)
        self.context.dpm.after(second.name, third.name)

        # First run: 
        # solves first and maybe second (depending on the order in the set)
        self.config.iterate_once()
        self.assertTrue(third.state == third.STATE_DONE)

        self.config.iterate_once()
        self.assertTrue(second.state == second.STATE_DONE)


        try:
            self.config.iterate_once()
        except cdist.Error:
            # Allow failing, because the third run may or may not be unecessary already,
            # depending on the order of the objects
            pass
        self.assertTrue(first.state == first.STATE_DONE)

    def test_unresolvable_requirements(self):
        """Ensure an exception is thrown for unresolvable depedencies"""

        # Create to objects depending on each other - no solution possible
        first   = self.object_index['__first/man']
        second  = self.object_index['__second/on-the']

        self.context.dpm.after(first.name, second.name)
        self.context.dpm.after(second.name, first.name)

        with self.assertRaises(cdist.UnresolvableRequirementsError):
            self.config.iterate_until_finished()

    def test_missing_requirements(self):
        """Throw an error if requiring something non-existing"""
        first = self.object_index['__first/man']
        self.context.dpm.after(first.name, '__first/not/exist')
        with self.assertRaises(cdist.UnresolvableRequirementsError):
            self.config.iterate_until_finished()

    def test_requirement_broken_type(self):
        """Unknown type should be detected in the resolving process"""
        first = self.object_index['__first/man']
        self.context.dpm.after(first.name, '__nosuchtype/not/exist')
        with self.assertRaises(cdist.core.cdist_type.NoSuchTypeError):
            self.config.iterate_until_finished()

    def test_requirement_singleton_where_no_singleton(self):
        """Missing object id should be detected in the resolving process"""
        first = self.object_index['__first/man']
        self.context.dpm.after(first.name, '__first')
        with self.assertRaises(cdist.core.cdist_object.MissingObjectIdError):
            self.config.iterate_until_finished()

# Currently the resolving code will simply detect that this object does
# not exist. It should probably check if the type is a singleton as well
# - but maybe only in the emulator - to be discussed.
#
#    def test_requirement_no_singleton_where_singleton(self):
#        """Missing object id should be detected in the resolving process"""
#        first = self.object_index['__first/man']
#        first.requirements = ['__singleton_test/foo']
#        with self.assertRaises(cdist.core.?????):
#            self.config.iterate_until_finished()
