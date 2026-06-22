FROM python:3.12-slim

WORKDIR /app
COPY . /app

EXPOSE 8000
CMD ["python", "web.py", "--host", "0.0.0.0", "--port", "8000"]
