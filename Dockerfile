FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝代码
COPY predictor/ ./predictor/

# 数据目录（SQLite 持久化用）
VOLUME ["/app/data"]

CMD ["python", "-m", "predictor.main"]
