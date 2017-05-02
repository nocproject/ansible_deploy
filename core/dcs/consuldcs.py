# -*- coding: utf-8 -*-
##----------------------------------------------------------------------
## Distributed coordinated storage
##----------------------------------------------------------------------
## Copyright (C) 2007-2017 The NOC Project
## See LICENSE for details
##----------------------------------------------------------------------

## Python modules
import uuid
import random
import os
import signal
## Third-party modules
from six.moves.urllib.parse import unquote
import tornado.gen
import tornado.ioloop
import consul.base
import consul.tornado
## NOC modules
from base import DCSBase

ConsulRepeatableErrors = consul.base.Timeout


class ConsulDCS(DCSBase):
    """
    Consul-based DCS
    
    URL format:
    consul://<address>[:<port>]/<kv root>?token=<token>&check_interval=<...>&check_timeout=<...>&release_after=<...>
    """
    DEFAULT_CONSUL_HOST = "consul"
    DEFAULT_CONSUL_PORT = 8500
    DEFAULT_CONSUL_CHECK_INTERVAL = 1
    DEFAULT_CONSUL_CHECK_TIMEOUT = 1
    DEFAULT_CONSUL_RELEASE = "1m"
    DEFAULT_CONSUL_SESSION_TTL = 10
    DEFAULT_CONSUL_LOCK_DELAY = 1
    DEFAULT_CONSUL_RETRY_TIMEOUT = 1

    def __init__(self, url, ioloop=None):
        self.name = None
        self.consul_host = self.DEFAULT_CONSUL_HOST
        self.consul_port = self.DEFAULT_CONSUL_PORT
        self.consul_prefix = "/"
        self.consul_token = None
        self.check_interval = self.DEFAULT_CONSUL_CHECK_INTERVAL
        self.check_timeout = self.DEFAULT_CONSUL_CHECK_TIMEOUT
        self.release_after = self.DEFAULT_CONSUL_RELEASE
        self.svc_name = None
        self.svc_address = None
        self.svc_port = None
        self.svc_check_url = None
        self.svc_id = None
        self.session = None
        super(ConsulDCS, self).__init__(url, ioloop)
        self.consul = consul.tornado.Consul(
            host=self.consul_host,
            port=self.consul_port,
            token=self.consul_token
        )
        self.session = None
        self.keep_alive_task = None

    def parse_url(self, u):
        if ":" in u.netloc:
            self.consul_host, port = u.netloc.rsplit(":", 1)
            self.consul_port = int(port)
        else:
            self.consul_host = u.netloc
        self.consul_prefix = u.path[1:]
        if self.consul_prefix.endswith("/"):
            self.consul_prefix = self.consul_prefix[:-1]
        for q in u.query.split("&"):
            if not q or "=" not in q:
                continue
            k, v = q.split("=", 1)
            v = unquote(v)
            if k == "token":
                self.consul_token = v
            elif k == "check_interval":
                self.check_interval = int(v)
            elif k == "check_timeout":
                self.check_timeout = int(v)
            elif k == "release_after":
                self.release_after = v

    @tornado.gen.coroutine
    def create_session(self):
        """
        Create consul session
        :return: 
        """
        self.logger.info("Creating session")
        # @todo: Add http healthcheck
        checks = ["serfHealth"]
        while True:
            try:
                self.session = yield self.consul.session.create(
                    name=self.name,
                    checks=checks,
                    behavior="delete",
                    lock_delay=1,
                    ttl=self.DEFAULT_CONSUL_SESSION_TTL
                )
                break
            except ConsulRepeatableErrors:
                yield tornado.gen.sleep(self.DEFAULT_CONSUL_RETRY_TIMEOUT)
                continue
        self.logger.info("Session id: %s", self.session)
        self.keep_alive_task = tornado.ioloop.PeriodicCallback(
            self.keep_alive,
            self.DEFAULT_CONSUL_SESSION_TTL * 1000 / 2,
            self.ioloop
        )
        self.keep_alive_task.start()

    @tornado.gen.coroutine
    def destroy_session(self):
        if self.session:
            self.logger.info("Destroying session %s", self.session)
            if self.keep_alive_task:
                self.keep_alive_task.stop()
                self.keep_alive_task = None
            try:
                yield self.consul.session.destroy(self.session)
            except ConsulRepeatableErrors:
                pass  # Ignore consul errors
            self.session = None

    @tornado.gen.coroutine
    def register(self, name, address, port, pool=None, lock=None):
        self.name = name
        self.svc_check_url = "http://%s:%s/health/" % (address, port)
        if lock:
            yield self.acquire_lock(lock)
        svc_id = self.session or str(uuid.uuid4())
        tags = [svc_id]
        if pool:
            tags += [pool]
        checks = consul.Check.http(
            self.svc_check_url,
            self.check_interval,
            "%ds" % self.check_timeout
        )
        checks["DeregisterCriticalServiceAfter"] = self.release_after
        while True:
            self.logger.info("Registering service %s: %s:%s (id=%s, pool=%s)",
                             name, address, port, svc_id, pool)
            try:
                r = yield self.consul.agent.service.register(
                    name=name,
                    service_id=svc_id,
                    address=address,
                    port=port,
                    tags=tags,
                    check=checks
                )
            except ConsulRepeatableErrors:
                yield tornado.gen.sleep(self.DEFAULT_CONSUL_RETRY_TIMEOUT)
                continue
            if r:
                self.svc_id = svc_id
            break
        raise tornado.gen.Return(r)

    @tornado.gen.coroutine
    def deregister(self):
        if self.session:
            try:
                yield self.destroy_session()
            except ConsulRepeatableErrors:
                pass
        if self.svc_id:
            try:
                yield self.consul.agent.service.deregister(self.svc_id)
            except ConsulRepeatableErrors:
                pass
            self.svc_id = None

    @tornado.gen.coroutine
    def keep_alive(self):
        if self.session:
            try:
                yield self.consul.session.renew(self.session)
            except consul.base.NotFound:
                self.logger.info("Session lost. Forcing quit")
                self.keep_alive_task.stop()
                self.keep_alive_task = None
                self.kill()
            except ConsulRepeatableErrors as e:
                self.logger.info("Cannot refresh session due to ignorable error: %s", e)
                pass
        else:
            self.keep_alive_task.stop()
            self.keep_alive_task = None

    def get_lock_path(self, lock):
        return self.consul_prefix + "/locks/" + lock

    @tornado.gen.coroutine
    def acquire_lock(self, name):
        if not self.session:
            yield self.create_session()
        key = self.get_lock_path(name)
        index = None
        while True:
            self.logger.info("Acquiring lock: %s", key)
            try:
                status = yield self.consul.kv.put(
                    key=key,
                    value=self.session,
                    acquire=self.session,
                    token=self.consul_token
                )
            except ConsulRepeatableErrors:
                yield tornado.gen.sleep(self.DEFAULT_CONSUL_RETRY_TIMEOUT)
                continue
            if status:
                break
            # Waiting for lock release
            while True:
                try:
                    index, data = yield self.consul.kv.get(
                        key=key,
                        index=index,
                        token=self.consul_token
                    )
                    if not data:
                        index = None  # Key has been deleted
                        yield tornado.gen.sleep(
                            self.DEFAULT_CONSUL_LOCK_DELAY * (0.5 + random.random())
                        )
                    break
                except ConsulRepeatableErrors:
                    yield tornado.gen.sleep(self.DEFAULT_CONSUL_RETRY_TIMEOUT)
        self.logger.info("Lock acquired")

    def kill(self):
        self.logger.info("Shooting self with SIGTERM")
        os.kill(os.getpid(), signal.SIGTERM)
