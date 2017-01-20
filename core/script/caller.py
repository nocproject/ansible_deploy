# -*- coding: utf-8 -*-
##----------------------------------------------------------------------
## Script caller client
##----------------------------------------------------------------------
## Copyright (C) 2007-2017 The NOC Project
## See LICENSE for details
##----------------------------------------------------------------------

## Python modules
from threading import Lock
import uuid
## NOC modules
from noc.core.service.client import RPCClient, RPCError
from noc.core.script.loader import loader

CALLING_SERVICE = "MTManager"
DEFAULT_IDLE_TIMEOUT = 60


class Session(object):
    """
    SA session
    """
    _sessions = {}
    _lock = Lock()

    class CallWrapper(object):
        def __init__(self, session, script):
            self.session = session
            self.script = script

        def __call__(self, **kwargs):
            return self.session._call_script(
                self.script, **kwargs
            )

    def __init__(self, object, idle_timeout=None):
        self._object = object
        self._id = str(uuid.uuid4())
        self._cache = {}
        self._idle_timeout = idle_timeout or DEFAULT_IDLE_TIMEOUT

    def __del__(self):
        self.close()

    def __getattr__(self, name):
        if name in self._cache:
            return self._cache[name]
        if not loader.has_script("%s.%s" % (
                self._object.profile_name, name)):
            raise AttributeError("Invalid script %s" % name)
        cw = Session.CallWrapper(self, name)
        self._cache[name] = cw
        return cw

    @classmethod
    def _get_url(cls, session, default=None):
        with cls._lock:
            url = cls._sessions.get(session)
            if not url and default:
                cls._sessions[session] = default
                url = default
        return url

    def _call_script(self, script, args, timeout=None):
        # Call SAE
        data = RPCClient(
            "sae",
            calling_service=CALLING_SERVICE
        ).get_credentials(self._object.id)
        # Get hints from session
        url = self._get_url(self._id, data["url"])
        # Call activator
        return RPCClient(
            "activator-%s" % self._object.pool.name,
            calling_service=CALLING_SERVICE,
            hints=[url]
        ).script(
            "%s.%s" % (self._object.profile_name, script),
            data["credentials"],
            data["capabilities"],
            data["version"],
            args,
            timeout
        )

    def close(self):
        url = self._get_url(self._id)
        if url:
            # Close at activator
            RPCClient(
                "activator-%s" % self._object.pool.name,
                calling_service=CALLING_SERVICE,
                hints=[url]
            ).close_session(self._id)
            # Remove from cache
            with self._lock:
                try:
                    del self._sessions[self._id]
                except KeyError:
                    pass


class SessionContext(object):
    def __init__(self, object, idle_timeout=None):
        self._object = object
        self._idle_timeout = idle_timeout or DEFAULT_IDLE_TIMEOUT
        self._session = Session(self._object, self._idle_timeout)
        self._object_scripts = None

    def __enter__(self):
        self._object_scripts = self._object.scripts
        self._object.scripts = self._session
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._object.scripts = self._object_scripts
        self._session.close()

    def __getattr__(self, name):
        if not name.startwith("_"):
            return getattr(self._session, name)
