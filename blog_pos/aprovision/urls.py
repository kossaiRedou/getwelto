from django.urls import path

from . import views

app_name = 'aprovision'

urlpatterns = [
    path('', views.reports_view, name='reports'),
    path('depenses/', views.depense_list, name='depense_list'),
    path('depenses/add/', views.depense_create, name='nouvelle_depense'),
    path('depenses/<int:pk>/delete/', views.depense_delete, name='depense_delete'),
    path('mouvements/', views.mouvement_list, name='mouvement_list'),
]
