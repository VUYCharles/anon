FROM python:3.12-slim

WORKDIR /app

# Dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY app.py .
COPY templates/ templates/
COPY static/ static/
COPY data/ data/

# Les données sont écrites dans /app/data : monter un volume en production
# pour persister tickets, audit et simulations.
VOLUME ["/app/data"]

EXPOSE 5000

# Serveur de production. SECRET_KEY à fournir via variable d'environnement.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "app:app"]
