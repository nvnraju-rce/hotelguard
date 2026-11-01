FROM python:3.15-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOTELGUARD_DB=/app/db/hotelguard.db \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .
RUN chmod +x docker-entrypoint.sh monitor.sh \
 && useradd --create-home --uid 10001 hotelguard \
 && mkdir -p /app/db /app/out \
 && chown -R hotelguard:hotelguard /app/db /app/out
USER hotelguard

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["streamlit", "run", "dashboard.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
