FROM python:3.11-slim

# Beállítjuk a munkakönyvtárat
WORKDIR /app

# Másoljuk a követelményeket és telepítjük őket
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Másoljuk a teljes kódot (a mappaszerkezeted szerint)
COPY . .

# FONTOS: Megadjuk a Pythonnak, hogy a /app mappát tekintse gyökérnek az importokhoz
ENV PYTHONPATH=/app

# FONTOS: Ne a fájlt indítsd direktben, hanem modulként a -m kapcsolóval
CMD ["python", "-m", "app.main"]
