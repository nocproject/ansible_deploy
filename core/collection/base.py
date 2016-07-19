# -*- coding: utf-8 -*-
##----------------------------------------------------------------------
## Collection utilities
##----------------------------------------------------------------------
## Copyright (C) 2007-2016 The NOC Project
## See LICENSE for details
##----------------------------------------------------------------------

## Python modules
import os
import zlib
import csv
import shutil
import hashlib
import uuid
from collections import namedtuple
import sys
## Third-party modules
import ujson
import bson
from mongoengine.fields import ListField, EmbeddedDocumentField
from noc.lib.fileutils import safe_rewrite


class Collection(object):
    PREFIX = "collections"
    CUSTOM_PREFIX = "custom/collections"
    STATE_COLLECTION = "noc.collectionstates"

    _MODELS = {}

    Item = namedtuple("Item", ["uuid", "path", "hash", "data"])

    def __init__(self, name, stdout=None):
        self.name = name
        self._model = None
        self.ref_cache = {}
        self._name_field = None
        self.stdout = stdout or sys.stdout

    def get_path(self):
        path = [os.path.join(self.PREFIX, self.name)]
        cp = os.path.join(self.CUSTOM_PREFIX, self.name)
        if os.path.isdir(cp):
            path = [cp] + path
        return path

    @classmethod
    def iter_collections(cls):
        from noc.models import COLLECTIONS, get_model
        for c in COLLECTIONS:
            cm = get_model(c)
            cn = cm._meta["json_collection"]
            cls._MODELS[cn] = cm
            yield Collection(cn)

    @property
    def model(self):
        if not self._model:
            if not self._MODELS:
                list(self.iter_collections())
            self._model = self._MODELS[self.name]
        return self._model

    @property
    def name_field(self):
        if not self._name_field:
            if hasattr(self.model, "name"):
                self._name_field = "name"
                return "name"
            else:
                for spec in self.model._meta["index_specs"]:
                    if spec["unique"] and len(spec["fields"]) == 1:
                        nf = spec["fields"][0][0]
                        self._name_field = nf
                        return nf
                raise ValueError("Cannot find unique index")
        else:
            return self._name_field

    def get_state(self):
        """
        Returns collection state as a dict of UUID -> hash
        :return:
        """
        from noc.lib.nosql import get_db

        coll = get_db()[self.STATE_COLLECTION]
        # Get state from database
        cs = coll.find_one({"_id": self.name})
        if cs:
            return ujson.loads(
                zlib.decompress(str(cs["state"]))
            )
        # Fallback to legacy local
        lpath = self.get_legacy_state_path()
        state = {}
        if os.path.exists(lpath):
            with open(lpath) as f:
                reader = csv.reader(f)
                reader.next()  # Skip header
                for name, uuid, path, hash in reader:
                    state[uuid] = hash
        return state

    def save_state(self, state):
        """
        Save collection state
        :param state:
        :return:
        """
        from noc.lib.nosql import get_db

        coll = get_db()[self.STATE_COLLECTION]
        coll.update({
            "_id": self.name,
        }, {
            "$set": {
                "state": bson.Binary(
                    zlib.compress(
                        ujson.dumps(state)
                    )
                )
            }
        }, upsert=True)
        # Remove legacy state
        lpath = self.get_legacy_state_path()
        if os.path.isfile(lpath):
            shutil.move(lpath, lpath + ".bak")

    def get_legacy_state_path(self):
        """
        Return legacy CSV state file path
        :return:
        """
        parts = self.name.split(".")
        return os.path.join("local", "collections",
                            parts[0], "%s.csv" % parts[1])

    def get_changed_status(self):
        """
        Return initially changed status
        :return:
        """
        return os.path.isfile(self.get_legacy_state_path())

    def get_items(self):
        """
        Returns dict of UUID -> Collection.Item
        containing new state
        :return:
        """
        items = {}
        for p in self.get_path():
            for root, dirs, files in os.walk(p):
                for cf in files:
                    if not cf.endswith(".json"):
                        continue
                    fp = os.path.join(root, cf)
                    with open(fp) as f:
                        data = f.read()
                    jdata = ujson.loads(data)
                    csum = hashlib.sha256(data).hexdigest()
                    items[jdata["uuid"]] = self.Item(
                        uuid=jdata["uuid"],
                        path=fp,
                        hash=csum,
                        data=jdata
                    )
        return items

    def dereference(self,  d, model=None):
        r = {}
        model = model or self.model
        for k in d:
            v = d[k]
            if k.startswith("$"):
                continue  # Ignore $name
            if k == "uuid":
                r["uuid"] = uuid.UUID(v)
                continue
            # Dereference ref__name lookups
            if "__" in k:
                # Lookup
                k, f = k.split("__")
                if k not in model._fields:
                    raise ValueError("Invalid lookup field: %s" % k)
                ref = model._fields[k].document_type
                v = self.lookup(ref, f, v)
            # Get field
            try:
                field = model._fields[k]
            except KeyError:
                continue  # Ignore unknown fields
            # Dereference ListFields
            if (type(field) == ListField and
                    isinstance(field.field, EmbeddedDocumentField)):
                edoc = field.field.document_type
                v = [edoc(**self.dereference(x, model=edoc)) for x in d[k]]
            r[str(k)] = v
        return r

    def lookup(self, ref, field, key):
        field = str(field)
        if ref not in self.ref_cache:
            self.ref_cache[ref] = {field: {}}
        if field not in self.ref_cache[ref]:
            self.ref_cache[ref][field] = {}
        if key in self.ref_cache[ref][field]:
            return self.ref_cache[ref][field][key]
        else:
            try:
                v = ref.objects.get(**{field: key})
            except ref.DoesNotExist:
                raise ValueError(
                    "lookup for %s.%s == '%s' has been failed" % (
                        ref._meta["collection"], field, key)
                )
            self.ref_cache[ref][field][key] = v
            return v

    def update_item(self, data):
        o = self.model.objects.filter(uuid=data["uuid"]).first()
        try:
            d = self.dereference(data)
        except ValueError:
            return False  # Partials
        if o:
            self.stdout.write(
                "[%s|%s] Updating %s\n" % (
                    self.name, data["uuid"],
                    getattr(o, self.name_field)
            ))
            for k in d:
                setattr(o, k, d[k])
        else:
            self.stdout.write(
                "[%s|%s] Creating %s\n" % (
                    self.name, data["uuid"],
                    data.get(self.name_field)
            ))
            o = self.model(**d)
        o.save()
        return True

    def delete_item(self, name, model, uuid):
        o = model.objects.filter(uuid=uuid).first()
        if not o:
            return
        self.stdout.write("[%s|%s] Deleting %s\n" % (
            name, uuid, getattr(o, self.name_field)
        ))
        o.delete()

    def sync(self):
        # Read collection from JSON files
        cdata = self.get_items()
        # Get previous state
        cs = self.get_state()
        #
        current_uuids = set(cs)
        new_uuids = set(cdata)
        changed = self.get_changed_status()
        #
        self.fix_uuids()
        partials = []
        # New items
        for u in new_uuids - current_uuids:
            if not self.update_item(cdata[u].data):
                partials += [u]
            changed = True
        # Changed items
        for u in new_uuids & current_uuids:
            if cs[u] != cdata[u].hash:
                if not self.update_item(cdata[u].data):
                    partials += [u]
                changed = True
        # Resolve partials
        while partials:
            np = []
            for u in partials:
                if not self.update_item(cdata[u].data):
                    np += [u]
            if len(np) == len(partials):
                # Cannot resolve partials
                raise ValueError(
                    "[%s] Cannot resolve references for %s" % (
                        self.name, ", ".join(partials))
                )
            partials = np
        # Deleted items
        for u in current_uuids - new_uuids:
            self.delete_item(u)
            changed = True
        # Save state
        if changed:
            state = dict((u, cdata[u].hash) for u in sorted(cdata))
            self.save_state(state)

    def fix_uuids(self):
        """
        Convert string UUIDs to binary
        :param name:
        :param model:
        :return:
        """
        n = 0
        bulk = self.model._get_collection().initialize_unordered_bulk_op()
        for d in self.model._get_collection().find(
            {
                "uuid": {"$type": "string"}
            },
            {
                "_id": 1,
                "uuid": 1
            }
        ):
            bulk.find({"_id": d["_id"]}).update({
                "$set": {
                    "uuid": uuid.UUID(d["uuid"])
                }
            })
            n += 1
        if n:
            self.stdout.write("[%s] Fixing %d UUID\n" % (
                self.name, n
            ))
            bulk.execute()

    @classmethod
    def install(cls, data):
        """
        Write data to the proper path
        :param data:
        :return:
        """
        c = Collection(data["$collection"])
        o = c.dereference(data)
        # Format JSON
        json_data = o.to_json()
        # Write
        path = os.path.join(
            cls.PREFIX,
            c.name,
            o.get_json_path()
        )
        c.stdout.write("[%s|%s] Installing %s\n" % (
            c.name, data["uuid"], path))
        safe_rewrite(
            path,
            json_data,
            mode=0o644
        )
