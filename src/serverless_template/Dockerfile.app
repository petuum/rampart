# Copyright 2023 Petuum, Inc. All Rights Reserved.

# Primary K8 Dockerfile for fastapi app

FROM tiangolo/uvicorn-gunicorn-fastapi:python3.7
ENV APP_MODULE app:app
ENV FUNC_CONFIG /mount/app/function_config.yaml

ENV GUNICORN_CONF /gunicorn_conf.py

COPY ./gunicorn_conf.py /gunicorn_conf.py
COPY ./app/requirements.txt ./requirements.txt
COPY ./start.sh /start.sh
RUN pip install -r requirements.txt

RUN chmod a+x /start.sh

WORKDIR /mount/app

ENTRYPOINT [ "/start.sh" ]