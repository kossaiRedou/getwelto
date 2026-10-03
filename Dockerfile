# WELTO POS — image de production (Coolify / Docker).
#
# Étape 1 : compile le CSS Tailwind avec le binaire autonome (pas de Node.js).
# Étape 2 : image Python légère, fichiers statiques précompressés, serveur uvicorn.

FROM python:3.12-slim AS css
ARG TAILWIND_VERSION=v4.3.3
ARG TARGETARCH
RUN ARCH=$([ "$TARGETARCH" = "arm64" ] && echo arm64 || echo x64) \
 && python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${ARCH}', '/usr/local/bin/tailwindcss')" \
 && chmod +x /usr/local/bin/tailwindcss
WORKDIR /src
COPY blog_pos/ .
RUN tailwindcss -i assets/app.css -o core/static/css/app.css --minify


FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WELTO_USER_DATA=/data \
    WEB_CONCURRENCY=2

WORKDIR /app
COPY blog_pos/requirements.txt .
RUN pip install -r requirements.txt

COPY blog_pos/ .
COPY --from=css /src/core/static/css/app.css core/static/css/app.css
RUN SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
 && useradd --create-home --uid 1000 welto \
 && mkdir -p /data/media /data/logs \
 && chown -R welto:welto /data

USER welto
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

# Migrations appliquées à chaque démarrage (sans effet si déjà à jour), puis serveur.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec uvicorn blog_pos.asgi:application --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${WEB_CONCURRENCY}"]
