"""Preferência individual e QR de divulgação, usando as sessões existentes."""
import io
import os
from functools import lru_cache
from html import escape
from typing import Literal
from urllib.parse import urlsplit

import qrcode
from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

class Preferencia(BaseModel):
    tema: Literal['claro', 'escuro', 'sistema']

def instalar(app, c):
    banco, usuario, dono, root = c['banco'], c['usuario'], c['dono'], c['ROOT']
    with banco() as db:
        db.execute("CREATE TABLE IF NOT EXISTS preferencias (id TEXT PRIMARY KEY, tema TEXT NOT NULL CHECK(tema IN ('claro','escuro','sistema')))")

    def conta(user):
        return user['papel'] + ':' + user['id']

    @app.get('/api/aparencia')
    def aparencia(request: Request):
        with banco() as db:
            user = usuario(request, db)
            key = conta(user)
            row = db.execute('SELECT tema FROM preferencias WHERE id=?', (key,)).fetchone()
            return {'tema': row['tema'] if row else 'sistema', 'conta': key}

    @app.put('/api/aparencia')
    def salvar(data: Preferencia, request: Request):
        with banco() as db:
            user = usuario(request, db, True)
            key = conta(user)
            db.execute('INSERT INTO preferencias(id,tema) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET tema=excluded.tema', (key, data.tema))
            return {'tema': data.tema, 'conta': key}

    def dados(request):
        with banco() as db:
            user = dono(request, db)
            shop = db.execute('SELECT slug FROM lojas WHERE id=?', (user['loja_id'],)).fetchone()
            config = c['config_da_loja'](db, user['loja_id'])
        # Use a origem configurada, nunca cabeçalhos Host fornecidos pelo visitante.
        base = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
        if not base and c['CLOUD']:
            raise HTTPException(503, 'Configure PUBLIC_BASE_URL com o endereço público do sistema.')
        if not base:
            base = 'http://127.0.0.1:8788'
        parsed = urlsplit(base)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment or (c['CLOUD'] and parsed.scheme != 'https'):
            raise HTTPException(503, 'O endereço público do sistema precisa ser configurado corretamente.')
        return {'nome': config['nome'], 'logo_url': config.get('logo_url',''), 'url': base + '/b/' + shop['slug']}

    @lru_cache(maxsize=128)
    def png(url):
        # Margem de quatro módulos e contraste fixo para leitura e impressão.
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=20, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(fill_color='black', back_color='white')
        out = io.BytesIO()
        image.save(out, format='PNG')
        return out.getvalue()

    @app.get('/api/qr-agendamento')
    def info(request: Request):
        return dados(request)

    @app.get('/api/qr-agendamento.png')
    def imagem(request: Request):
        data = dados(request)
        return Response(png(data['url']), media_type='image/png',
                        headers={'Content-Disposition': 'attachment; filename="qr-agendamento.png"'})

    @app.get('/qr-agendamento/imprimir', response_class=HTMLResponse)
    def imprimir(request: Request):
        data = dados(request)
        logo = escape(data['logo_url'], quote=True)
        # Configuração já validada no servidor; nunca aceitar HTML da loja.
        logo_html = ('<img class="logo" src="' + logo + '" alt="Logo da barbearia">') if logo.startswith('https://') else ''
        return """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>QR Code de Agendamento</title>
<style>
@page{size:A4;margin:15mm}*{box-sizing:border-box}body{margin:0;background:#eee;font-family:system-ui,sans-serif;color:#171717}
.tools{text-align:center;padding:20px}button,a{display:inline-block;padding:12px 20px;border:0;border-radius:8px;background:#dfa94d;color:#171717;text-decoration:none;font:600 16px system-ui;cursor:pointer}
.poster{width:min(100%,180mm);margin:0 auto;padding:12mm;text-align:center;border:1px solid #c8c8c8;background:#fff;border-radius:12px}
.logo{width:24mm;height:24mm;object-fit:contain}.shop{font-size:20pt;overflow-wrap:anywhere;margin:4mm 0 8mm}
h1{font-size:28pt;line-height:1.15;margin:6mm 0}p{font-size:13pt;line-height:1.5}.qr{width:min(100%,105mm);height:auto;display:block;margin:8mm auto}
.url{font-size:9pt;overflow-wrap:anywhere;color:#444}.tagline{font-weight:700;font-size:16pt}
@media(max-width:600px){.poster{padding:20px}h1{font-size:26px}.shop{font-size:22px}}
@media print{body{background:#fff}.tools{display:none}.poster{width:100%;max-width:180mm;border:1px solid #aaa;break-inside:avoid}.qr{max-width:105mm}a{color:inherit}}
</style></head><body><div class="tools"><button id="print">Imprimir / salvar PDF</button> <a href="/painel#qr">Voltar ao painel</a></div>
<section class="poster">""" + logo_html + '<h2 class="shop">' + escape(data['nome']) + """</h2>
<h1>AGENDE SEU HORÁRIO</h1><p>Aponte a câmera do seu celular para o QR Code.</p>
<img class="qr" src="/api/qr-agendamento.png" alt="QR Code para agendar nesta barbearia">
<p class="tagline">Agende em poucos segundos</p><p class="url">""" + escape(data['url']) + """</p></section>
<script>document.getElementById('print').onclick=async()=>{await Promise.all([...document.images].map(img=>img.decode().catch(()=>{})));window.print();};</script></body></html>"""

    @app.get('/appearance.js')
    def script():
        return FileResponse(root / 'appearance.js', media_type='application/javascript')

    @app.get('/appearance.css')
    def css():
        return FileResponse(root / 'appearance.css', media_type='text/css')
