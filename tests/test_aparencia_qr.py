"""Teste isolado: QR real, isolamento, preferências e compatibilidade do backup."""
import os
import io
import json
import tempfile
from pathlib import Path
import importlib.util

os.environ.pop('RENDER', None)
os.environ.pop('DATABASE_URL', None)
os.environ['PUBLIC_BASE_URL']='https://agenda.example.com'
os.environ['BILLING_ENABLED']='false'
from fastapi.testclient import TestClient
from PIL import Image

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'teste.db')
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('qr_app',root/'app.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    a,b,guest=TestClient(mod.app),TestClient(mod.app),TestClient(mod.app)
    password='SenhaTeste!12345'
    for client,slug in [(a,'loja-a'),(b,'loja-b')]:
        r=client.post('/api/cadastro',json={'aceite_termos':True,'nome':slug,'slug':slug,'email':slug+'@example.com','senha':password})
        assert r.status_code==201,r.text
    ah={'X-CSRF-Token':a.get('/api/sessao').json()['csrf']}
    bh={'X-CSRF-Token':b.get('/api/sessao').json()['csrf']}
    assert guest.get('/api/qr-agendamento').status_code==401
    assert guest.get('/api/qr-agendamento.png').status_code==401
    assert guest.get('/qr-agendamento/imprimir').status_code==401
    assert guest.get('/api/aparencia').status_code==401
    ai,bi=a.get('/api/qr-agendamento').json(),b.get('/api/qr-agendamento').json()
    assert ai['url']=='https://agenda.example.com/b/loja-a'
    assert bi['url']=='https://agenda.example.com/b/loja-b'
    assert a.get('/api/qr-agendamento?loja_id=outra').json()==ai
    ap,bp=a.get('/api/qr-agendamento.png'),b.get('/api/qr-agendamento.png')
    assert ap.content!=bp.content and ap.headers['content-type']=='image/png'
    assert 'attachment' in ap.headers['content-disposition']
    for response,url in [(ap,ai['url']),(bp,bi['url'])]:
        image=Image.open(io.BytesIO(response.content))
        assert image.width>=600 and image.width==image.height
        assert image.convert('RGB').getpixel((0,0))==(255,255,255)
        # Decodificador independente confirma os pixels, não apenas o texto usado pelo gerador.
        if os.environ.get('QR_DECODE_TEST')=='1':
            import cv2
            import numpy as np
            pixels=cv2.imdecode(np.frombuffer(response.content,np.uint8),cv2.IMREAD_COLOR)
            decoded,points,_=cv2.QRCodeDetector().detectAndDecode(pixels)
            assert decoded==url and points is not None,decoded
    poster=a.get('/qr-agendamento/imprimir')
    assert poster.status_code==200 and 'AGENDE SEU HORÁRIO' in poster.text and 'loja-a' in poster.text
    assert 'loja-b' not in poster.text and '@page{size:A4' in poster.text
    assert guest.get('/b/loja-a').status_code==200
    assert guest.get('/api/publico/loja-a/configuracao').json()['nome']=='loja-a'
    assert a.get('/api/aparencia').json()['tema']=='sistema'
    for theme in ['claro','escuro','sistema']:
        assert a.put('/api/aparencia',json={'tema':theme}).status_code==403
        assert a.put('/api/aparencia',json={'tema':theme},headers=ah).status_code==200
        assert a.get('/api/aparencia').json()['tema']==theme
        assert b.get('/api/aparencia').json()['tema']=='sistema'
    assert a.put('/api/aparencia',json={'tema':'invalido'},headers=ah).status_code==422
    assert a.put('/api/aparencia',json={'tema':'claro'},headers={**ah,'Origin':'https://intruso.example'}).status_code==403
    assert a.put('/api/aparencia',json={'tema':'escuro'},headers=ah).status_code==200
    a.post('/api/logout',headers=ah)
    a.post('/api/login',json={'email':'loja-a@example.com','senha':password})
    assert a.get('/api/aparencia').json()['tema']=='escuro'
    ah={'X-CSRF-Token':a.get('/api/sessao').json()['csrf']}
    cfg=a.get('/api/configuracao').json()
    cfg['barbeiros']=[{'id':'prof','nome':'Profissional'}]
    assert a.put('/api/configuracao',json=cfg,headers=ah).status_code==200
    invite=a.post('/api/equipe/prof/convite',json={'email':'prof@example.com'},headers=ah)
    assert invite.status_code==201,invite.text
    # A chave do token segue o formato que o núcleo existente retorna.
    token=invite.json()['link'].split('#')[-1]
    staff=TestClient(mod.app)
    r=staff.post('/api/convite/aceitar',json={'token':token,'senha':password})
    assert r.status_code==201,r.text
    sh={'X-CSRF-Token':staff.get('/api/sessao').json()['csrf']}
    assert staff.get('/api/qr-agendamento').status_code==403
    assert staff.get('/api/qr-agendamento.png').status_code==403
    assert staff.get('/qr-agendamento/imprimir').status_code==403
    assert staff.put('/api/aparencia',json={'tema':'claro'},headers=sh).status_code==200
    assert a.get('/api/aparencia').json()['tema']=='escuro'
    assert b.get('/api/aparencia').json()['tema']=='sistema'
    payload=mod.backup_payload()
    tables=payload['tabelas']
    assert len(tables['preferencias'])==2
    backup=Path(tmp)/'backup.json';backup.write_text(json.dumps(payload),encoding='utf-8')
    restore_spec=importlib.util.spec_from_file_location('restore_qr',root/'restaurar_backup.py')
    restore=importlib.util.module_from_spec(restore_spec);restore_spec.loader.exec_module(restore)
    restore.ler(backup)
    del payload['tabelas']['preferencias'];backup.write_text(json.dumps(payload),encoding='utf-8')
    assert restore.ler(backup)['preferencias']==[]
    assert guest.get('/appearance.js').status_code==200 and guest.get('/appearance.css').status_code==200
    print('OK: QR decodificável, download, impressão, página pública, CSRF, dono/equipe/lojas, persistência e backup anterior.')
