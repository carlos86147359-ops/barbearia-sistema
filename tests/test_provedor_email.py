"""Testa o contrato HTTPS de envio sem transmitir mensagens reais."""
import importlib.util,json,os,tempfile
from pathlib import Path
from unittest.mock import patch

with tempfile.TemporaryDirectory() as tmp:
    os.environ['BARBER_DB_PATH']=str(Path(tmp)/'email.db')
    for key in ('DATABASE_URL','RENDER','BREVO_API_KEY','RESEND_API_KEY','EMAIL_PROVIDER'):os.environ.pop(key,None)
    spec=importlib.util.spec_from_file_location('email_provider_app',Path(__file__).resolve().parents[1]/'app.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    os.environ.update(EMAIL_FROM='Grupo Havo <sender@example.com>',PUBLIC_BASE_URL='https://example.com',EMAIL_PROVIDER='brevo')
    assert not m.email_pronto()
    os.environ['BREVO_API_KEY']='test-only-brevo-key'
    assert m.email_pronto()
    class Answer:
        status=201
        def __enter__(self):return self
        def __exit__(self,*args):pass
    with patch('urllib.request.urlopen',return_value=Answer()) as network:
        m.enviar_email('recipient@example.com','Confirmação','Mensagem de teste','test-user','verificar')
        req=network.call_args.args[0];body=json.loads(req.data)
        assert req.full_url=='https://api.brevo.com/v3/smtp/email'
        assert req.get_header('Api-key')=='test-only-brevo-key'
        assert body['sender']=={'name':'Grupo Havo','email':'sender@example.com'}
        assert body['to']==[{'email':'recipient@example.com'}] and body['textContent']=='Mensagem de teste'
    os.environ.update(EMAIL_PROVIDER='resend',RESEND_API_KEY='test-only-resend-key')
    assert m.email_pronto()
    with patch('urllib.request.urlopen',return_value=Answer()) as network:
        m.enviar_email('recipient@example.com','Confirmação','Mensagem de teste','test-user','verificar')
        req=network.call_args.args[0]
        assert req.full_url=='https://api.resend.com/emails' and req.get_header('Authorization')=='Bearer test-only-resend-key'
        assert json.loads(req.data)['text']=='Mensagem de teste'
    os.environ['EMAIL_PROVIDER']='desconhecido';assert not m.email_pronto()
print('OK: Brevo e Resend via HTTPS, remetente e autenticação, sem envio real.')
