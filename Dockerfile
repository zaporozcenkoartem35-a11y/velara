FROM python:3.11-slim

# Установка рабочей директории
WORKDIR /app

# Отключение буферизации вывода Python (для мгновенных логов)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Копирование и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Команда запуска
CMD ["python", "main.py"]
