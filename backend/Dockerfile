# 后端：FastAPI + SQLAlchemy（构建上下文 = backend/）
FROM python:3.11-slim

WORKDIR /srv

# 国内网络：pip 走清华镜像。用 ENV 设 PIP_INDEX_URL，构建隔离的子进程
# （装 setuptools 等 build 依赖）也会继承,避免连 pypi.org 超时。
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 先装依赖（利用层缓存），再拷代码
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# 数据落到挂载卷；备份目录也在卷内，随 NAS 快照一起保护
ENV EXAM_TRACKER_DIR=/data \
    EXAM_TRACKER_BACKUP_DIR=/data/backups \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
