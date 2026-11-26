from flask import current_app
from redis import Redis
from rq import Queue

QUEUE_NAME = "algojudge"


def get_redis():
    return Redis.from_url(current_app.config["REDIS_URL"])


def get_queue():
    return Queue(QUEUE_NAME, connection=get_redis())


def enqueue(func, *args, **kwargs):
    return get_queue().enqueue(func, *args, job_timeout=300, retry=None, **kwargs)
