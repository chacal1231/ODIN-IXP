FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home ingester \
    && mkdir -p /var/lib/bmp-ingester && chown ingester /var/lib/bmp-ingester
COPY bmp_ingester.py /app/bmp_ingester.py
USER ingester
CMD ["python3", "-u", "/app/bmp_ingester.py"]
