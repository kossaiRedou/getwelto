from django.urls import path

from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('forgot-password/sent/', views.forgot_password_sent_view, name='forgot_password_sent'),
    path('reset/<uidb64>/<token>/', views.reset_password_view, name='reset_password'),

    path('list/', views.user_list_view, name='user_list'),
    path('create/', views.user_create_view, name='user_create'),
    path('<int:pk>/update/', views.user_update_view, name='user_update'),
    path('<int:pk>/delete/', views.user_delete_view, name='user_delete'),
    path('<int:pk>/password/', views.change_password_view, name='change_password'),
    path('my-password/', views.my_password_change_view, name='my_password_change'),
    path('settings/', views.app_settings_view, name='app_settings'),
]
