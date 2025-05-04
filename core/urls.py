# core/urls.py

from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import views as auth_views

from newsclip.views import (
    SignUpView,
    dashboard,
    ClientCreateView,
    ClientUpdateView,
    client_news,
    fetch_news_view,
    bulk_update_news,
    client_reports,
    generate_report_view,
    download_report,
)

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    path('reports/', include('reports_app.urls', namespace='reports_app')),
    # Raiz -> dashboard
    path('', lambda req: redirect('dashboard'), name='root_redirect'),
    path('dashboard/', login_required(dashboard), name='dashboard'),
    


    # Autenticação padrão Django
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # allauth (se você usa)
    path('accounts/', include('allauth.urls')),

    # Cadastro
    path('signup/', SignUpView.as_view(), name='signup'),

    # Clientes
    path('clients/add/', login_required(ClientCreateView.as_view()), name='client_add'),
    path('clients/<int:pk>/edit/', login_required(ClientUpdateView.as_view()), name='client_edit'),

    # Notícias por cliente
    path('dashboard/<int:client_id>/news/',           login_required(client_news),        name='client_news'),
    path('dashboard/<int:client_id>/news/fetch/',     login_required(fetch_news_view),    name='fetch_news'),
    path('dashboard/<int:client_id>/news/bulk-update/', login_required(bulk_update_news), name='bulk_update_news'),

    # Relatórios
    path('dashboard/<int:client_id>/reports/',            login_required(client_reports),          name='client_reports'),
    path('dashboard/<int:client_id>/reports/generate/',   login_required(generate_report_view),    name='generate_report_view'),
    path('dashboard/<int:client_id>/download/<str:filename>/', login_required(download_report), name='download_report'),
]