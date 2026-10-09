# Adapted from gpsaggese/umd_classes at 60df5bc966d6da403eb54ee059372edc5cf20099.
# Use Python 3.11 to match the already tested local Quant research environment.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace
COPY requirements.txt /tmp/financial-sentiment-requirements.txt
RUN pip install --no-cache-dir -r /tmp/financial-sentiment-requirements.txt
EXPOSE 8888
CMD ["bash"]
