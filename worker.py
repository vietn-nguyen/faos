from rq import SimpleWorker

from app import create_app
from app.queue import get_queue, get_redis
from app.services.jobs import reset_stuck

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        reset_stuck()
        queue = get_queue()
        worker = SimpleWorker([queue], connection=get_redis())
        worker.work(with_scheduler=False)
