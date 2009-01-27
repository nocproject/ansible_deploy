from django.conf.urls.defaults import *
from django.contrib import admin
admin.autodiscover()

handler404="noc.main.views.handler404"

urlpatterns = patterns('',
    # For debugging purposes only. Overriden by lighttpd/apache
     (r'^static/(?P<path>.*)$', 'django.views.static.serve', {'document_root': 'static'}),
     (r'^doc/(?P<path>.*)$',    'django.views.static.serve', {'document_root': 'share/doc/users_guide/html/'}),
    # 
     (r'^$',      include('noc.main.urls')),
     (r'^admin/(.*)', admin.site.root),
     (r'^accounts/login/$', 'django.contrib.auth.views.login', {'template_name':'template/login.html'}),
     (r'^main/',  include('noc.main.urls')),
     (r'^sa/',  include('noc.sa.urls')),
     (r'^fm/', include('noc.fm.urls')),
     (r'^cm/',  include('noc.cm.urls')),
     (r"^ip/", include("noc.ip.urls")),
     (r"^peer/", include("noc.peer.urls")),
     (r"^dns/", include("noc.dns.urls")),
)
