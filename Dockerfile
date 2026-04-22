FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the data directory exists for blockchain.json persistence
RUN mkdir -p data

EXPOSE 5000

ENV SIMULATION_MODE=True \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    FLASK_DEBUG=False \
    AUTO_MINE=True \
    SECRET_KEY=change-me-in-production

CMD ["python", "run.py"]
