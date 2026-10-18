FROM python:3.11-slim
WORKDIR /app
RUN useradd -m app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER app
ENV DBAGENT_DB=/home/app/data/retail.db
RUN python -m dbagent.cli demo
CMD ["python", "-m", "dbagent.server"]
