FROM python:3.14-slim

ADD requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt

ADD hls_encrypt_watcher.py /hls_encrypt_watcher.py

CMD ["echo", "override CMD in docker-compose.yml"]
