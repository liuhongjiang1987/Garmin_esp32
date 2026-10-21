# 教练接口容器。回答文字，并把原文合成语音。不负责从佳明下载。
# 群晖访问不到 Docker Hub，基础镜像和 Python 包走国内镜像。
FROM docker.1ms.run/library/python:3.12-slim

WORKDIR /app/agent

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    deepagents \
    langchain \
    langgraph \
    langchain-openai \
    pydantic \
    python-dotenv \
    fitdecode \
    fastapi \
    uvicorn

COPY agent /app/agent

ENV COACH_BIND=0.0.0.0
ENV COACH_PORT=8765
EXPOSE 8765

CMD ["python", "-m", "src.cli", "serve"]
