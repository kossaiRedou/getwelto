from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path

from order import views as order_views

urlpatterns = [
    path('healthz', lambda request: HttpResponse('ok', content_type='text/plain'), name='healthz'),
    path('admin/', admin.site.urls),
    path('users/', include('users.urls')),

    # Caisse
    path('', order_views.pos_view, name='pos'),
    path('api/catalog/', order_views.api_catalog, name='api_catalog'),
    path('api/checkout/', order_views.api_checkout, name='api_checkout'),

    # Ventes
    path('sales/', order_views.order_list, name='order_list'),
    path('sales/<int:pk>/', order_views.order_detail, name='order_detail'),
    path('sales/<int:pk>/ticket/', order_views.order_ticket, name='order_ticket'),
    path('sales/<int:pk>/pdf/', order_views.invoice_pdf_view, name='invoice_pdf'),
    path('sales/<int:pk>/payment/', order_views.order_add_payment, name='order_add_payment'),
    path('sales/<int:pk>/payment/<int:payment_id>/delete/', order_views.order_delete_payment,
         name='order_delete_payment'),
    path('sales/<int:pk>/cancel/', order_views.order_cancel, name='order_cancel'),

    path('dashboard/', order_views.dashboard_view, name='dashboard'),

    path('products/', include('product.urls')),
    path('clients/', include('client.urls')),
    path('aprovision/', include('aprovision.urls')),
]

# Fichiers média (logo, signature) : servis par Django, volumétrie faible.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    from django.views.static import serve as media_serve
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', media_serve, {'document_root': settings.MEDIA_ROOT}),
    ]
