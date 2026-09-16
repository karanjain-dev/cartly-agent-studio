FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY service/requirements.txt /app/service/requirements.txt
RUN pip install --no-cache-dir -r service/requirements.txt
COPY cartly /app/cartly
COPY service /app/service
COPY data /app/data
COPY policy.md /app/policy.md
COPY prompts/current.md /app/prompts/current.md
RUN useradd --uid 10001 --create-home cartly
USER cartly
EXPOSE 8000
CMD ["python", "-m", "service.production"]
