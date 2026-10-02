"""Arquivos instaláveis e isolamento entre conteúdo público e agenda privada."""
import importlib.util,json,os,struct,tempfile,zlib
from pathlib import Path
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    for key in ('DATABASE_URL','RENDER','BREVO_API_KEY','RESEND_API_KEY','ADMIN_EMAILS'):os.environ.pop(key,None)
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'pwa.db')
    spec=importlib.util.spec_from_file_location('pwa_test_app',ROOT/'app.py')
    app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
    client=TestClient(app.app)
    r=client.get('/manifest.webmanifest');assert r.status_code==200
    assert r.headers['content-type'].startswith('application/manifest+json')
    manifest=r.json();assert manifest['display']=='standalone' and manifest['start_url']=='/painel' and manifest['scope']=='/'
    for icon in manifest['icons']:
        r=client.get(icon['src']);assert r.status_code==200 and r.headers['content-type']=='image/png'
        size=int(icon['sizes'].split('x')[0]);png=r.content
        assert png[:8]==b'\x89PNG\r\n\x1a\n' and struct.unpack('>II',png[16:24])==(size,size)
        offset=8;compressed=b''
        while offset<len(png):
            length=struct.unpack('>I',png[offset:offset+4])[0];kind=png[offset+4:offset+8];data=png[offset+8:offset+8+length]
            assert struct.unpack('>I',png[offset+8+length:offset+12+length])[0]==zlib.crc32(kind+data)
            if kind==b'IDAT':compressed+=data
            offset+=12+length
        assert len(zlib.decompress(compressed))==size*(size*3+1)
    for path in ('/sw.js','/pwa.js','/offline.html'):
        r=client.get(path);assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert client.get('/api/agendamentos').status_code==401
    assert client.get('/api/configuracao').status_code==401
    assert client.get('/api/gestao/operacao').status_code==401
    assert client.get('/icons/icon-0.png').status_code==404
    assert 'manifest.webmanifest' in client.get('/painel').text
print('OK: manifesto, ícones, scripts de instalação, aviso offline e proteção da agenda.')

