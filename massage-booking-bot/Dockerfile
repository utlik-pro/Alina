FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt && pip check

# Copy application code
COPY . .

# Expose port for webhook
EXPOSE 10000

# Run bot (webhook mode when RENDER=true, polling otherwise)
CMD ["python", "run.py"]
