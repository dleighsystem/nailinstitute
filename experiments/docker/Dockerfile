FROM python:3.11-slim

WORKDIR /workspace

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy experiment code
COPY experiments/ /workspace/experiments/

# Default: run all experiments
CMD ["python", "-m", "experiments.run_all"]
