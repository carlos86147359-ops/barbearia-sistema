import io,json,os,tempfile,importlib.util
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient

def picture(size=(1600,1000)):
    out=io.BytesIO();Image.new('RGB',size,(150,100,30)).save(out,format='PNG');return out.getvalue()

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'imagens.db')
    for key in ('DATABASE_URL','RENDER','ADMIN_EMAILS','BILLING_ENABLED','CLOUDINARY_CLOUD_NAME','CLOUDINARY_API_KEY','CLOUDINARY_API_SECRET'):os.environ.pop(key,None)
    spec=importlib.util.spec_from_file_location('images_app',Path(__file__).parents[1]/'app.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    import imagens
    a,b,public=TestClient(mod.app),TestClient(mod.app),TestClient(mod.app)
    headers=[]
    for i,c in enumerate((a,b)):
        r=c.post('/api/cadastro',json={'nome':'Loja '+str(i),'slug':'loja-'+str(i),'email':f'dono{i}@example.com','senha':'SenhaTeste!12345','aceite_termos':True});assert r.status_code==201
        headers.append({'X-CSRF-Token':r.json()['csrf']})
    assert public.get('/api/imagens/status').status_code==401
    assert a.get('/api/imagens/status').json()=={'disponivel':False}
    raw=picture()
    assert a.post('/api/imagens/logo',content=raw,headers=headers[0]).status_code==503
    os.environ.update(CLOUDINARY_CLOUD_NAME='teste-cloud',CLOUDINARY_API_KEY='key-teste',CLOUDINARY_API_SECRET='segredo-teste')
    assert a.get('/api/imagens/status').json()=={'disponivel':True}
    seen=[]
    def fake_send(data,shop,kind):
        image=Image.open(io.BytesIO(data));assert image.format=='WEBP';assert max(image.size)<=imagens.LIMITS['foto' if kind.startswith('profissional-') else kind][0];assert len(data)<=imagens.LIMITS['foto' if kind.startswith('profissional-') else kind][1]
        seen.append((shop,kind));return 'https://res.cloudinary.com/teste-cloud/image/upload/v1/barbersaas/'+shop+'/'+kind+'.webp'
    with patch.object(imagens,'enviar',side_effect=fake_send):
        assert public.post('/api/imagens/logo',content=raw).status_code==401
        assert a.post('/api/imagens/logo',content=raw).status_code==403
        assert a.post('/api/imagens/logo',content=b'x'*600001,headers=headers[0]).status_code==413
        assert a.post('/api/imagens/logo',content=b'<svg></svg>',headers=headers[0]).status_code==422
        assert a.post('/api/imagens/logo',content=picture((3000,3000)),headers=headers[0]).status_code==422
        assert a.post('/api/imagens/outro',content=raw,headers=headers[0]).status_code==404
        for kind in ('logo','capa'):
            r=a.post('/api/imagens/'+kind,content=raw,headers=headers[0]);assert r.status_code==200,r.text
            assert a.get('/api/configuracao').json()[kind+'_url']==r.json()['url']
            assert public.get('/api/publico/loja-0/configuracao').json()[kind+'_url']==r.json()['url']
        assert b.get('/api/configuracao').json().get('logo_url','')==''
        before=a.get('/api/configuracao').json()['logo_url']
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return json.dumps({'public_id':'barbersaas/loja/logo','secure_url':'https://res.cloudinary.com/teste-cloud/image/upload/v123/barbersaas/loja/logo.webp'}).encode()
    def provider(req,timeout):
        assert req.full_url=='https://api.cloudinary.com/v1_1/teste-cloud/image/upload'
        assert req.get_header('Authorization').startswith('Basic ')
        assert b'segredo-teste' not in req.data
        assert b'barbersaas/loja/logo' in req.data
        return Reply()
    with patch.object(imagens.urllib.request,'urlopen',side_effect=provider):
        assert imagens.enviar(raw,'loja','logo').startswith('https://res.cloudinary.com/')
    with patch.object(imagens,'enviar',side_effect=mod.HTTPException(502,'Falha de teste')):
        assert a.post('/api/imagens/logo',content=raw,headers=headers[0]).status_code==502
        assert a.get('/api/configuracao').json()['logo_url']==before
    cfg=a.get('/api/configuracao').json();cfg['barbeiros']=[{'id':'prof','nome':'Profissional'}]
    assert a.put('/api/configuracao',json=cfg,headers=headers[0]).status_code==200
    cfgb=b.get('/api/configuracao').json();cfgb['barbeiros']=[{'id':'prof','nome':'Outra equipe'}]
    assert b.put('/api/configuracao',json=cfgb,headers=headers[1]).status_code==200
    with patch.object(imagens,'enviar',side_effect=fake_send):
        assert public.post('/api/equipe/prof/foto',content=raw).status_code==401
        assert a.post('/api/equipe/prof/foto',content=raw).status_code==403
        assert a.post('/api/equipe/inexistente/foto',content=raw,headers=headers[0]).status_code==404
        assert a.post('/api/imagens/foto',content=raw,headers=headers[0]).status_code==404
        r=a.post('/api/equipe/prof/foto',content=raw,headers=headers[0]);assert r.status_code==200,r.text
        photo=r.json()['url'];assert '/profissional-prof.webp' in photo
        assert public.get('/api/publico/loja-0/configuracao').json()['barbeiros'][0]['foto_url']==photo
        assert not b.get('/api/configuracao').json()['barbeiros'][0].get('foto_url')
        r=b.post('/api/equipe/prof/foto',content=raw,headers=headers[1]);assert r.status_code==200
        assert r.json()['url']!=photo
        # Clientes antigos que não conhecem o campo preservam a foto.
        cfg=a.get('/api/configuracao').json();del cfg['barbeiros'][0]['foto_url']
        assert a.put('/api/configuracao',json=cfg,headers=headers[0]).status_code==200
        assert a.get('/api/configuracao').json()['barbeiros'][0]['foto_url']==photo
        invalid=a.get('/api/configuracao').json();invalid['barbeiros'][0]['foto_url']='javascript:alert(1)'
        assert a.put('/api/configuracao',json=invalid,headers=headers[0]).status_code==422
        assert a.delete('/api/equipe/prof/foto').status_code==403
        assert public.delete('/api/equipe/prof/foto').status_code==401
        assert a.delete('/api/equipe/prof/foto',headers=headers[0]).status_code==200
        assert a.get('/api/configuracao').json()['barbeiros'][0]['foto_url']==''
        assert b.get('/api/configuracao').json()['barbeiros'][0]['foto_url']==r.json()['url']
        assert a.post('/api/equipe/prof/foto',content=raw,headers=headers[0]).status_code==200
    with patch.object(imagens,'enviar',side_effect=mod.HTTPException(502,'Falha de teste')):
        assert a.post('/api/equipe/prof/foto',content=raw,headers=headers[0]).status_code==502
        assert a.get('/api/configuracao').json()['barbeiros'][0]['foto_url']==photo
    invite=a.post('/api/equipe/prof/convite',json={'email':'prof@example.com'},headers=headers[0]).json()
    staff=TestClient(mod.app);r=staff.post('/api/convite/aceitar',json={'token':invite['link'].split('#')[1],'senha':'SenhaTeste!12345'});assert r.status_code==201
    sh={'X-CSRF-Token':r.json()['csrf']}
    assert staff.get('/api/imagens/status').status_code==403
    assert staff.post('/api/imagens/logo',content=raw,headers=sh).status_code==403
    assert staff.post('/api/equipe/prof/foto',content=raw,headers=sh).status_code==403
    assert staff.delete('/api/equipe/prof/foto',headers=sh).status_code==403
    assert 'segredo-teste' not in public.get('/image-upload.js').text
    print('OK: imagem real recomprimida, limites, CSRF, papéis, isolamento, persistência, erro preservando URL e segredo somente no servidor.')
