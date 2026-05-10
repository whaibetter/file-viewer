FROM python:3.11-slim

# 系统依赖：procps(ps), iproute2(ip), proc(/proc), mount, coreutils(df)
RUN apt-get update && \
    apt-get install -y --no-install-recommends procps iproute2 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh

ENV DOCKER_CONTAINER=1

EXPOSE 9001

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python3", "cloudrein-server.py"]
