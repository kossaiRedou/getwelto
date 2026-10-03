# -*- coding: utf-8 -*-
"""Configuration ASGI de WELTO."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blog_pos.settings')

application = get_asgi_application()
