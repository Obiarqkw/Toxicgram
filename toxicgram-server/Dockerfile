FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py admin.html admin.js admin.css plush_pepe.json original_gifts.json bananchik_palette.b64 tecno_charger.json ./
ENV TOXICGRAM_DB=/data/toxicgram.sqlite3
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
