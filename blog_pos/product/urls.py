from django.urls import path

from . import views

app_name = 'product'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('add/', views.product_create, name='add_product'),
    path('<int:pk>/edit/', views.product_edit, name='edit_product'),
    path('<int:pk>/stock/', views.product_stock, name='quick_stock'),
    path('<int:pk>/toggle/', views.product_toggle, name='toggle_product'),
    path('<int:pk>/delete/', views.product_delete, name='delete_product'),
    path('categories/', views.category_management, name='category_management'),
    path('categories/<int:pk>/delete/', views.category_delete, name='delete_category'),
]
