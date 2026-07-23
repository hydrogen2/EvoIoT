FROM python:3.11-slim
RUN pip install --no-cache-dir psycopg2-binary
WORKDIR /app
COPY server.py .
EXPOSE 8899
CMD ["python", "server.py"]
