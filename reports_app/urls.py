from django.urls import path
from .views import MonthlyReportView

app_name = 'reports_app'

urlpatterns = [
    path('<int:client_id>/<int:year>/<int:month>/', MonthlyReportView.as_view(), name='monthly'),
]
