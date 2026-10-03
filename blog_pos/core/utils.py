import datetime
from decimal import Decimal, InvalidOperation

CENT = Decimal('0.01')
NNBSP = ' '


def format_money(value):
    """38000 → « 38 000 » ; 1250.5 → « 1 250,50 » (centimes affichés seulement s'il y en a)."""
    if value in (None, ''):
        value = 0
    try:
        amount = Decimal(value).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    sign = '-' if amount < 0 else ''
    amount = abs(amount)
    units = int(amount)
    cents = int((amount - units) * 100)
    text = f'{units:,}'.replace(',', NNBSP)
    if cents:
        text += f',{cents:02d}'
    return sign + text


def to_cents(value):
    return int(Decimal(value).quantize(CENT) * 100)


def parse_iso_date(value, default=None):
    if not value:
        return default
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return default


def json_etag_response(request, data):
    """Réponse JSON dont l'ETag est l'empreinte du contenu : 304 (quelques octets) si inchangé.

    GZipMiddleware rend l'ETag « faible » (W/"…") : on compare sans ce préfixe.
    """
    import hashlib
    import json

    from django.http import HttpResponse

    body = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    etag = '"' + hashlib.md5(body.encode()).hexdigest() + '"'
    if request.headers.get('If-None-Match', '').replace('W/', '') == etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(body, content_type='application/json')
    response['ETag'] = etag
    response['Cache-Control'] = 'private, no-cache'
    return response
