FROM		python:3.10-alpine
LABEL		author="Noiless"

# adduser created a group with GUID 1000 and name noiless for the user below automatically
RUN		    adduser --disabled-password --gecos "" --uid 1000 noiless
USER		noiless

COPY		--chown=noiless requirements.txt .
RUN		    pip install -r requirements.txt

WORKDIR		/src
ENTRYPOINT	python3 main.py
