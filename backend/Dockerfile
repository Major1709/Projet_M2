FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

# L'extra embeddings est optionnel a la construction. Sans lui l'image reste
# autour de 200 Mo ; avec, elle depasse 2,5 Go. Une image qui n'indexe rien n'a
# pas a porter un moteur d'inference.
ARG WITH_EMBEDDINGS=0

# torch depuis l'index CPU, imperativement avant l'extra : l'index par defaut
# sert la variante CUDA, soit plus de 2 Go de bibliotheques pour un GPU que le
# conteneur ne possede pas.
RUN python -m pip install . \
    && if [ "$WITH_EMBEDDINGS" = "1" ]; then \
         python -m pip install --index-url https://download.pytorch.org/whl/cpu torch \
         && python -m pip install ".[embeddings]"; \
       fi

# Le modele se telecharge au premier usage, environ 1 Go. Ce repertoire est
# monte depuis l'hote en developpement pour que le telechargement ne recommence
# pas a chaque reconstruction.
ENV HF_HOME=/home/app/.cache/huggingface
RUN mkdir -p "$HF_HOME" && chown -R app:app /home/app

USER app

EXPOSE 8000

STOPSIGNAL SIGTERM

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
