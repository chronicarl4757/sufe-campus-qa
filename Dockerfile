# HuggingFace Spaces（Docker SDK）/ 通用容器部署
# BGE-M3 约 2GB，Spaces 上请开持久存储并挂到 /data
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

ENV HF_HOME=/data/hf
EXPOSE 7860

CMD ["uvicorn", "sufe_qa.app.server:app", "--host", "0.0.0.0", "--port", "7860"]
