# -*- coding: utf-8 -*-
##----------------------------------------------------------------------
## Django URL dispatcher.
##----------------------------------------------------------------------
## Copyright (C) 2007-2009 The NOC Project
## See LICENSE for details
##----------------------------------------------------------------------
"""
"""
from noc.lib.app.site import site, patterns

##
## Discover all applications
##
site.autodiscover()
##
## Install URL handlers
##
urlpatterns = patterns("",
    (r"^jsi18n/$", "django.views.i18n.javascript_catalog",
        {"packages": "django.conf"})
) + site.urls

from noc.main.models import CustomField
CustomField.install_fields()
