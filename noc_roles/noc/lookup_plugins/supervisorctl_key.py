# -*- coding: utf-8 -*-
# Generate mongod keyfile

# Python modules
import os

# Ansible modules
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, inject=None, **kwargs):
        ret = []

        # this can happen if the variable contains a string, strictly not desired for lookup
        # plugins, but users may try it, so make it work.
        if not isinstance(terms, list):
            terms = [terms]

        for term in terms:
            params = term.split()
            relpath = params[0]
            path = self._loader.path_dwim(relpath)
            if os.path.exists(path):
                with open(path) as f:
                    key = f.read().strip()
            else:
                d = os.path.dirname(path)
                if not os.path.exists(d):
                    os.makedirs(d, mode=0o700)
                # Generate key file
                key = os.urandom(48).encode("base64").strip()
                with open(path, "w") as f:
                    os.chmod(path, 0o600)
                    f.write(key)
            ret += [key]
        return ret
