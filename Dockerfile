FROM python:3.12-slim
WORKDIR /site
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY public/ ./public/
COPY server.py schema.sql rich_text.py ai_review.py auth.py authorization.py editorial_api.py manage_accounts.py ./
USER 65534:65534
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=8s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["sh", "-c", "python server.py && exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 2 --timeout 120 --worker-tmp-dir /tmp --no-control-socket server:app"]
