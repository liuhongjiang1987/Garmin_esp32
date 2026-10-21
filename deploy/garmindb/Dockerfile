# GarminDB 同步容器。只负责从 Garmin Connect 下载并写入 SQLite，不对外开端口。
# 群晖直连 Docker Hub 会超时，基础镜像和 Python 包都走国内镜像。
FROM docker.1ms.run/library/python:3.12-slim

# 固定在镜像里安装。fitdecode 用来从游泳 FIT 读取每一趟。
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple garmindb fitdecode

# 导入成功后，入口会接着计算尚未入库的游泳指标。
COPY incremental_activity_import.py garmindb_entry.py compute_swim_metrics.py /opt/
COPY swimcore /opt/swimcore

WORKDIR /root
ENTRYPOINT ["python", "/opt/garmindb_entry.py"]
