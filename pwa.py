"""Arquivos públicos da instalação; nenhum dado da agenda é armazenado offline."""
import struct
import zlib
from functools import lru_cache
from fastapi.responses import Response


@lru_cache(maxsize=2)
def icone(size):
    # Símbolo de poste de barbearia, com margem para recorte de ícones maskable.
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            u, v = x / size, y / size
            color = (11, 16, 24)
            if .35 <= u <= .65 and .24 <= v <= .76:
                color = [(255, 196, 94), (247, 249, 252), (55, 115, 182)][int((u + v) * 18) % 3]
            if .30 <= u <= .70 and (.19 <= v <= .24 or .76 <= v <= .81):
                color = (255, 196, 94)
            rows.extend(color)
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def instalar(app, root):
    for path, filename, mime in [
        ('/manifest.webmanifest', 'manifest.webmanifest', 'application/manifest+json'),
        ('/sw.js', 'sw.js', 'text/javascript'),
        ('/pwa.js', 'pwa.js', 'text/javascript'),
        ('/offline.html', 'offline.html', 'text/html'),
    ]:
        # A fábrica evita transformar valores internos em parâmetros da URL.
        def endpoint_factory(filename, mime):
            def endpoint():
                return Response((root / filename).read_text(encoding='utf-8'), media_type=mime, headers={'Cache-Control': 'no-cache'})
            return endpoint
        app.add_api_route(path, endpoint_factory(filename, mime), methods=['GET'], include_in_schema=False)
    for size in (192, 512):
        def icon_factory(size):
            def endpoint():
                return Response(icone(size), media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})
            return endpoint
        app.add_api_route(f'/icons/icon-{size}.png', icon_factory(size), methods=['GET'], include_in_schema=False)

