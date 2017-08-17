# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------
# Clickhouse Dictionaries
# ----------------------------------------------------------------------
# Copyright (C) 2007-2017 The NOC Project
# See LICENSE for details
# ----------------------------------------------------------------------

# Python modules
from __future__ import absolute_import
import operator
import itertools
import os
# Third-party modules
import six
import cachetools
# NOC modules
from .fields import BaseField
from noc.config import config

__all__ = ["Dictionary"]


class DictionaryBase(type):
    def __new__(mcs, name, bases, attrs):
        cls = type.__new__(mcs, name, bases, attrs)
        cls._fields = {}
        cls._meta = DictionaryMeta(
            name=getattr(cls.Meta, "name", None),
            layout=getattr(cls.Meta, "layout", None),
            lifetime_min=getattr(cls.Meta, "lifetime_min", 3600),
            lifetime_max=getattr(cls.Meta, "lifetime_max", 3600),
        )
        assert cls._meta.layout in (None, "flat", "hashed")
        for k in attrs:
            if isinstance(attrs[k], BaseField):
                cls._fields[k] = attrs[k]
                cls._fields[k].name = k
        cls._fields_order = sorted(
            cls._fields, key=lambda x: cls._fields[x].field_number
        )
        return cls


class DictionaryMeta(object):
    def __init__(self, name=None, layout=None,
                 lifetime_min=None, lifetime_max=None):
        self.name = name
        self.layout = layout
        self.lifetime_min = lifetime_min
        self.lifetime_max = lifetime_max


class Dictionary(six.with_metaclass(DictionaryBase)):
    class Meta:
        name = None
        layout = None
        lifetime_min = None
        lifetime_max = None

    _lookup_cache = cachetools.LRUCache(10000)
    _collection = None
    _seq = None

    @classmethod
    def iter_cls(cls):
        """
        Generator yielding all known dictionaries
        :return:
        """
        for f in os.listdir("core/bi/dictionaries"):
            if not f.endswith(".py") or f.startswith("_"):
                continue
            yield Dictionary.get_dictionary_class(f[:-3])

    @classmethod
    def get_config(cls):
        """
        Generate XML config
        :return:
        """
        x = [
            "<dictionaries>",
            "    <comment>Generated by NOC, do not change manually</comment>",
            "    <dictionary>",
            "        <name>%s</name>" % cls._meta.name,
            "        <lifetime>",
            "            <min>%s</min>" % cls._meta.lifetime_min,
            "            <max>%s</max>" % cls._meta.lifetime_max,
            "        </lifetime>",
            "        <layout>",
            "            <%s />" % cls._meta.layout,
            "        </layout>",
            "        <source>",
            "            <file>",
            "                <path>%s/%s.tsv</path>" % (config.path.bi_dict_data_prefix, cls._meta.name),
            "                <format>TabSeparated</format>",
            "            </file>",
            "        </source>",
            "        <structure>",
            "             <id>",
            "                 <name>id</name>",
            "             </id>"
        ]
        for f in cls._fields_order:
            ff = cls._fields[f]
            hier = getattr(cls._fields[f], "is_self_reference", False)
            x += [
                "             <attribute>",
                "                 <name>%s</name>" % ff.name,
                "                 <type>%s</type>" % ff.db_type,
                "                 <null_value>Unknown</null_value>",
                "                 <hierarchical>%s</hierarchical>" % "true" if hier else "false",
                "             </attribute>"
            ]
        x += [
            "        </structure>",
            "    </dictionary>",
            "</dictionaries>"
        ]
        return "\n".join(x)

    @classmethod
    def get_dictionary_class(cls, name):
        """
        Returns dictionary class referred by name
        @todo: Process custom/
        :param name:
        :return:
        """
        m = __import__("noc.core.bi.dictionaries.%s" % name, {}, {}, "*")
        for a in dir(m):
            o = getattr(m, a)
            if not hasattr(o, "_meta"):
                continue
            if getattr(o._meta, "name", None) == name:
                return o
        return None

    @classmethod
    def get_collection_name(cls):
        return "noc.bi_dict_%s" % cls._meta.name

    @classmethod
    def get_collection(cls):
        if not cls._collection:
            from noc.lib.nosql import get_db
            cls._collection = get_db()[cls.get_collection_name()]
            cls._collection.create_index("id", unique=True)
        return cls._collection

    @classmethod
    @cachetools.cachedmethod(operator.attrgetter("_lookup_cache"))
    def lookup(cls, value):
        c = cls.get_collection()
        record = cls.get_record(value)
        d = c.find_one({"_id": record["_id"]}, {"_id": 0, "id": 1})
        if d:
            # Found
            return d["id"]
        # Not found
        if cls._seq is None:
            # Find current sequence value
            current = 1
            for d in c.find({}, {"_id": 0, "id": 1}).sort("id", -1).limit(1):
                current = d["id"] + 1
            cls._seq = itertools.count(current)
        # Insert
        record["id"] = next(cls._seq)
        c.insert(record)
        return record["id"]

    @classmethod
    def get_record(cls, value):
        """
        Return dict instance to populate dictionary
        :param value:
        :return:
        """
        raise NotImplementedError()

    @classmethod
    def get_field_type(cls, name):
        """
        Returns field type

        :param name:
        :return:
        """
        return cls._fields[name].db_type

    @classmethod
    def dump(cls, out):
        for d in cls.get_collection().find({}):
            out.write("%s\t%s\n" % (
                str(d["id"]),
                "\t".join(str(d.get(f, "")).replace("\n", "").replace("\t", "") for f in cls._fields)
            ))
