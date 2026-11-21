"""``treemap serve``: the HTTP API the phone's scan page (and later Home Assistant) uses.

:mod:`treemap.api.app` has the endpoints, :mod:`treemap.api.http` the HTTP and CORS
plumbing, :mod:`treemap.api.leds` the test patterns.
"""

from treemap.api.app import API_VERSION, Api, lan_address
from treemap.api.http import HttpServer

__all__ = ["API_VERSION", "Api", "HttpServer", "lan_address"]
