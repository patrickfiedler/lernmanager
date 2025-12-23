FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create data and uploads directories
RUN mkdir -p /app/data /app/static/uploads

# Expose port
EXPOSE 8080

# Run with waitress
CMD ["python", "run.py"]
