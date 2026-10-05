from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('inscription/', views.signup_view, name='signup'),
    path('inscription/merci/', views.signup_done_view, name='signup_done'),
    path('boutiques/', views.shop_list, name='shop_list'),
    path('boutiques/nouvelle/', views.shop_create, name='shop_create'),
    path('boutiques/<int:pk>/', views.shop_edit, name='shop_edit'),
    path('boutiques/choisir/', views.switch_shop, name='switch_shop'),
]
