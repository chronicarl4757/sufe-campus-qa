# HuggingFace Spaces（Docker SDK）/ 通用容器部署
# BGE-M3 约 2GB，Spaces 上请开持久存储并挂到 /data
FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

# 锁定安装：以 uv.lock 为准导出依赖，杜绝二次解析漂移
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# 项目本体（依赖已按锁文件就位，--no-deps 避免重新解析）
COPY src ./src
RUN pip install --no-cache-dir --no-deps . \
    && useradd -m appuser && mkdir -p /data && chown -R appuser:appuser /app /data

USER appuser
ENV HF_HOME=/data/hf
EXPOSE 7860

CMD ["uvicorn", "sufe_qa.app.server:app", "--host", "0.0.0.0", "--port", "7860"]
