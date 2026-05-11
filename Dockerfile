FROM python:3.12-slim

WORKDIR /app

COPY src /app/src

RUN mkdir -p /app/logs /app/config

EXPOSE 8080

CMD ["python", "/app/src/app.py"]
