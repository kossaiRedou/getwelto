from django.urls import path

from . import views

app_name = 'client'

urlpatterns = [
    path('', views.client_list, name='client_list'),
    path('add/', views.client_create, name='add_client'),
    path('<int:pk>/', views.client_detail, name='client_detail'),
    path('<int:pk>/edit/', views.client_edit, name='edit_client'),
    path('<int:pk>/delete/', views.client_delete, name='delete_client'),
    path('api/search/', views.api_search, name='api_search'),
    path('api/create/', views.api_create, name='api_create'),
]
