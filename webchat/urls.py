from django.urls import path

from . import views

app_name = "webchat"

urlpatterns = [
    path("session/", views.SessionStartView.as_view(), name="session"),
    path("verify/request-code/", views.RequestCodeView.as_view(), name="request-code"),
    path("verify/confirm-code/", views.ConfirmCodeView.as_view(), name="confirm-code"),
    path("message/", views.SendMessageView.as_view(), name="message"),
    path("location/", views.ShareLocationView.as_view(), name="location"),
    path("upload-id/", views.UploadIDView.as_view(), name="upload-id"),
    path("messages/", views.PollMessagesView.as_view(), name="messages"),
]
