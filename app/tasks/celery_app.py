from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "xinbaoyan-business",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_publish_retry=False,
    broker_connection_timeout=1,
    broker_transport_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    result_backend_transport_options={"socket_connect_timeout": 1, "socket_timeout": 1},
    task_routes={"judge.execute": {"queue": "judge"}},
)
