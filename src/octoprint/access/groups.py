# coding=utf-8
from __future__ import absolute_import, division, print_function

__author__ = "Marc Hannappel <salandora@gmail.com>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2017 The OctoPrint Project - Released under terms of the AGPLv3 License"

import logging
import os
from functools import partial

import yaml

from past.builtins import basestring

from octoprint.settings import settings
from octoprint.util import atomic_write
from octoprint.access.permissions import Permissions, OctoPrintPermission
from flask_principal import Need, Permission

ADMIN_GROUP = "admins"
DEFAULT_ADMIN_PERMISSIONS = [Permissions.ADMIN]
"""Default admin permissions are the legacy permissions from before 1.4.0"""

USER_GROUP = "users"
DEFAULT_USER_PERMISSIONS = [Permissions.STATUS,
                            Permissions.CONNECTION,
                            Permissions.WEBCAM,
                            Permissions.FILES_UPLOAD,
                            Permissions.FILES_DOWNLOAD,
                            Permissions.FILES_DELETE,
                            Permissions.FILES_SELECT,
                            Permissions.PRINT,
                            Permissions.MONITOR_TERMINAL,
                            Permissions.CONTROL,
                            Permissions.SLICE,
                            Permissions.TIMELAPSE_LIST,
                            Permissions.TIMELAPSE_ADMIN]
"""Default user permissions are the legacy permissions from before 1.4.0"""

GUEST_GROUP = "guests"
DEFAULT_GUEST_PERMISSIONS = [Permissions.STATUS,
                             Permissions.WEBCAM,
                             Permissions.FILES_DOWNLOAD,
                             Permissions.TIMELAPSE_LIST,
                             Permissions.MONITOR_TERMINAL]
"""Default guest permissions are the legacy permissions from before 1.4.0"""


GroupNeed = partial(Need, 'group')
GroupNeed.__doc__ = """A need with the method preset to `"group"`."""


class GroupPermission(Permission):
	def __init__(self, key):
		need = GroupNeed(key)
		super(GroupPermission, self).__init__(need)


class GroupManager(object):
	def __init__(self):
		self._logger = logging.getLogger(__name__)
		self._group_change_listeners = []
		self._init_defaults()

	@property
	def groups(self):
		return []

	@property
	def admin_group(self):
		return self.find_group(ADMIN_GROUP)

	@property
	def user_group(self):
		return self.find_group(USER_GROUP)

	@property
	def guest_group(self):
		return self.find_group(GUEST_GROUP)

	def _init_defaults(self):
		self.add_group(ADMIN_GROUP,
		               "Admins",
		               "Administrators",
		               DEFAULT_ADMIN_PERMISSIONS,
		               changeable=False,
		               removable=False,
		               save=False)
		self.add_group(USER_GROUP,
		               "Users",
		               "Logged in users",
		               DEFAULT_USER_PERMISSIONS,
		               default=True,
		               removable=False,
		               save=False)
		self.add_group(GUEST_GROUP,
		               "Guests",
		               "Logged out guests",
		               DEFAULT_GUEST_PERMISSIONS,
		               removable=False,
		               save=False)

	def register_listener(self, listener):
		self._group_change_listeners.append(listener)

	def unregister_listener(self, listener):
		self._group_change_listeners.remove(listener)

	def add_group(self, key, name, description, permissions, default=False, removable=True, changeable=True, save=True, notify=True):
		pass

	def update_group(self, key, description=None, permissions=None, default=None, save=True, notify=True):
		pass

	def remove_group(self, key, save=True, notify=True):
		pass

	def find_group(self, key):
		return None

	def _to_permissions(self, *permissions):
		return filter(lambda x: x is not None,
		              [Permissions.find(permission) for permission in permissions])

	def _from_permissions(self, *permissions):
		return [permission.key for permission in permissions]

	def _to_group(self, group):
		# noinspection PyCompatibility
		if isinstance(group, Group):
			return group
		elif isinstance(group, basestring):
			return self.find_group(group)
		elif isinstance(group, dict):
			return self.find_group(group.get("key"))
		else:
			return None

	def _notify_listeners(self, action, group, *args, **kwargs):
		method = "on_group_{}".format(action)
		for listener in self._group_change_listeners:
			try:
				getattr(listener, method)(group, *args, **kwargs)
			except:
				self._logger.exception("Error notifying listener {!r} via {}".format(listener, method))

class GroupChangeListener(object):

	def on_group_added(self, group):
		pass

	def on_group_removed(self, group):
		pass

	def on_group_permissions_changed(self, group, added=None, removed=None):
		pass


class FilebasedGroupManager(GroupManager):
	def __init__(self, path=None):
		if path is None:
			path = settings().get(["accessControl", "groupfile"])
			if path is None:
				path = os.path.join(settings().getBaseFolder("base"), "groups.yaml")

		self._groupfile = path
		self._groups = dict()
		self._dirty = False

		GroupManager.__init__(self)

		self._load()

	def _load(self):
		if os.path.exists(self._groupfile) and os.path.isfile(self._groupfile):
			try:
				with open(self._groupfile, "r") as f:
					data = yaml.safe_load(f)
					for key, attributes in data.items():
						if key in self._groups and not self._groups[key].is_changable():
							# group is already there (from the defaults most likely) and may not be changed -> bail
							continue

						self._groups[key] = Group(key, attributes.get("name", ""),
						                          description=attributes.get("description", ""),
						                          permissions=self._to_permissions(*attributes.get("permissions", [])),
						                          default=attributes.get("default", False),
						                          removable=attributes.get("removable",
						                                                   not attributes.get("specialGroup", False)),
						                          changeable=attributes.get("changeable", True))
			except:
				self._logger.exception("Error while loading groups from file {}".format(self._groupfile))

	def _save(self, force=False):
		if self._groupfile is None or not self._dirty and not force:
			return

		data = dict()
		for key in self._groups.keys():
			group = self._groups[key]
			data[key] = dict(
				name=group._name,
				description=group._description,
				permissions=self._from_permissions(*group._permissions),
				default=group._default,
				removable=group.is_removeable(),
				changeable=group.is_changable()
			)

		with atomic_write(self._groupfile, "wb", permissions=0o600, max_permissions=0o666) as f:
			import yaml
			yaml.safe_dump(data, f, default_flow_style=False, indent="    ", allow_unicode=True)
			self._dirty = False
		self._load()

	@property
	def groups(self):
		return list(self._groups.values())

	@property
	def default_groups(self):
		return [group for group in self._groups.values() if group.is_default()]

	def find_group(self, key):
		if key is None:
			return None
		return self._groups.get(key)

	def add_group(self, key, name, description, permissions, default=False, removable=True,
	              changeable=True, overwrite=False, notify=True, save=True):
		if key in self._groups.keys() and not overwrite:
			raise GroupAlreadyExists(key)

		if not permissions:
			permissions = []

		permissions = self._to_permissions(*permissions)
		assert(all(map(lambda p: isinstance(p, OctoPrintPermission), permissions)))

		group = Group(key, name,
		              description=description,
		              permissions=permissions,
		              default=default,
		              changeable=changeable,
		              removable=removable)
		self._groups[key] = group

		if save:
			self._dirty = True
			self._save()

		if notify:
			self._notify_listeners("added", group)

	def remove_group(self, key, save=True, notify=True):
		"""Removes a Group by key"""
		group = self._to_group(key)
		if group is None:
			raise UnknownGroup(key)

		if not group.is_removeable():
			raise GroupUnremovable(key)

		del self._groups[key]
		self._dirty = True

		if save:
			self._save()

		if notify:
			self._notify_listeners("removed", group)

	def update_group(self, key, description=None, permissions=None, default=None, save=True, notify=True):
		group = self._to_group(key)
		if group is None:
			raise UnknownGroup(key)

		if not group.is_changable():
			raise GroupCantBeChanged(key)

		if description is not None and description != group.get_description():
			group.change_description(description)
			self._dirty = True

		notifications = []

		if permissions is not None:
			permissions = self._to_permissions(*permissions)
			assert (all(map(lambda p: isinstance(p, OctoPrintPermission), permissions)))

			removed_permissions = list(set(group._permissions) - set(permissions))
			added_permissions = list(set(permissions) - set(group._permissions))

			if removed_permissions:
				self._dirty |= group.remove_permissions_from_group(removed_permissions)
			if added_permissions:
				self._dirty |= group.add_permissions_to_group(added_permissions)

			notifications.append((("permissions_changed", group),
			                      dict(added=added_permissions, removed=removed_permissions)))

		if default is not None:
			group.change_default(default)
			self._dirty = True

		if self._dirty:
			if save:
				self._save()

			if notify:
				for args, kwargs in notifications:
					self._notify_listeners(*args, **kwargs)


class GroupAlreadyExists(Exception):
	def __init__(self, key):
		Exception.__init__(self, "Group %s already exists" % key)


class UnknownGroup(Exception):
	def __init__(self, key):
		Exception.__init__(self, "Unknown group: %s" % key)


class GroupUnremovable(Exception):
	def __init__(self, key):
		Exception.__init__(self, "Group can't be removed: %s" % key)


class GroupCantBeChanged(Exception):
	def __init__(self, key):
		Exception.__init__(self, "Group can't be changed: %s" % key)


class Group(object):
	def __init__(self, key, name, description="", permissions=None, default=False, removable=True, changeable=True):
		self._key = key
		self._name = name
		self._description = description
		self._permissions = permissions
		self._default = default
		self._removable = removable
		self._changeable = changeable

	def as_dict(self):
		from octoprint.access.permissions import OctoPrintPermission
		return dict(
			key=self.key,
			name=self.get_name(),
			description=self._description,
			permissions=map(lambda p: p.key, self._permissions),
			needs=OctoPrintPermission.convert_needs_to_dict(self.needs),
			default=self._default,
			removable=self._removable,
			changeable=self._changeable
		)

	@property
	def key(self):
		return self._key

	def get_name(self):
		return self._name

	def get_description(self):
		return self._description

	def is_default(self):
		return self._default

	def is_changable(self):
		return self._changeable

	def is_removeable(self):
		return self._removable

	def add_permissions_to_group(self, permissions):
		"""Adds a list of permissions to a group"""
		if not self.is_changable():
			raise GroupCantBeChanged(self.key)

		# Make sure the permissions variable is of type list
		if not isinstance(permissions, list):
			permissions = [permissions]

		assert(all(map(lambda p: isinstance(p, OctoPrintPermission), permissions)))

		dirty = False
		for permission in permissions:
			if permissions not in self.permissions:
				self._permissions.append(permission)
				dirty = True

		return dirty

	def remove_permissions_from_group(self, permissions):
		"""Removes a list of permissions from a group"""
		if not self.is_changable():
			raise GroupCantBeChanged(self.key)

		# Make sure the permissions variable is of type list
		if not isinstance(permissions, list):
			permissions = [permissions]

		assert(all(map(lambda p: isinstance(p, OctoPrintPermission), permissions)))

		dirty = False
		for permission in permissions:
			if permission in self._permissions:
				self._permissions.remove(permission)
				dirty = True

		return dirty

	def change_default(self, default):
		"""Changes the default flag of a Group"""
		if not self.is_changable():
			raise GroupCantBeChanged(self.key)

		self._default = default

	def change_description(self, description):
		"""Changes the description of a group"""
		self._description = description

	@property
	def permissions(self):
		if Permissions.ADMIN in self._permissions:
			return Permissions.all()

		return filter(lambda p: p is not None, self._permissions)

	@property
	def needs(self):
		needs = set()
		needs.add(GroupNeed(self.key))
		for p in self.permissions:
			needs = needs.union(p.needs)

		return needs

	def has_permission(self, permission):
		if Permissions.ADMIN.get_name() in self._permissions:
			return True

		return permission.needs.issubset(self.needs)

	def __repr__(self):
		return '{}("{}", "{}", description="{}", permissions={!r}, ' \
		       'default={}, removable={}, changeable={})'.format(self.__class__.__name__,
                                                                 self._key,
		                                                         self._name,
		                                                         self._description,
		                                                         self._permissions,
		                                                         bool(self._default),
		                                                         bool(self._removable),
		                                                         bool(self._changeable))

	def __hash__(self):
		return self.key.__hash__()

	def __eq__(self, other):
		return isinstance(other, Group) and other.key == self.key



