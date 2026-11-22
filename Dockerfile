FROM python:3.12-slim
WORKDIR /app
COPY charlie_replay.py .
CMD ["python3", "charlie_replay.py", "--loop"]
