"""E-mail, bloqueios, autoatendimento, histórico e cópias de recuperação."""
import hashlib
import json
import os
import secrets
import time
import urllib.request
from email.utils import parseaddr
from datetime import date, datetime, timedelta

from fastapi import BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field

VERSAO_TERMOS='2026-10-02'
TABLES={
    'preferencias':['id','tema'],
    'lojas':['id','slug','configuracao'],
    'usuarios':['id','loja_id','email','senha'],
    'funcionarios':['id','loja_id','barbeiro_id','email','senha','ativo'],
    'assinaturas':['loja_id','vencimento'],
    'cortesias':['loja_id','administrador_id','criado_em','motivo'],
    'pagamentos':['id','loja_id','referencia','valor_centavos','confirmado_por','confirmado_em','vencimento'],
    'agendamentos':['id','cliente_nome','cliente_telefone','barbeiro_nome','servico_nome','data_hora','preco','criado_em','status','inicio','duracao_minutos','loja_id','barbeiro_id','servico_id','comissao_pct'],
    'bloqueios':['id','loja_id','barbeiro_id','inicio','fim','motivo'],
    'links_clientes':['reserva_id','token'],
    'emails_confirmados':['usuario_id','email','confirmado_em'],
    'aceites':['usuario_id','versao','aceito_em'],
}

from produtos import TABLES as PRODUCT_TABLES
TABLES.update(PRODUCT_TABLES)
from mensalistas import TABLES as MONTHLY_TABLES
TABLES.update(MONTHLY_TABLES)
from notificacoes import TABLES as PUSH_TABLES
TABLES.update(PUSH_TABLES)

class EmailPedido(BaseModel):
    email: str = Field(min_length=3,max_length=150)

class TokenPedido(BaseModel):
    token: str = Field(min_length=20,max_length=100)

class NovaSenha(TokenPedido):
    senha: str = Field(min_length=10,max_length=128)

class HorariosCliente(TokenPedido):
    data: date

class AlteracaoCliente(TokenPedido):
    acao: str
    data: date | None = None
    horario: str | None = None

class Bloqueio(BaseModel):
    barbeiro_id: str = Field(default='',max_length=50)
    inicio: datetime
    fim: datetime
    motivo: str = Field(min_length=2,max_length=100)

class SenhaAtual(BaseModel):
    senha: str = Field(min_length=10,max_length=128)

def instalar(app,c):
    banco=c['banco']; dono=c['dono']; usuario=c['usuario']; admin=c['administrador']; br=c['BRASIL']
    with banco() as db:
        db.execute('CREATE TABLE IF NOT EXISTS bloqueios (id TEXT PRIMARY KEY,loja_id TEXT NOT NULL,barbeiro_id TEXT NOT NULL,inicio TEXT NOT NULL,fim TEXT NOT NULL,motivo TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS links_clientes (reserva_id BIGINT PRIMARY KEY,token TEXT UNIQUE NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS tokens_email (token TEXT PRIMARY KEY,usuario_id TEXT NOT NULL,email TEXT NOT NULL,acao TEXT NOT NULL,expira BIGINT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS emails_confirmados (usuario_id TEXT PRIMARY KEY,email TEXT NOT NULL,confirmado_em TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS aceites (usuario_id TEXT PRIMARY KEY,versao TEXT NOT NULL,aceito_em TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS eventos_email (id TEXT PRIMARY KEY,usuario_id TEXT NOT NULL,acao TEXT NOT NULL,status TEXT NOT NULL,criado_em TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS copias (id TEXT PRIMARY KEY,criado_em TEXT NOT NULL,administrador_id TEXT NOT NULL,checksum TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS bloqueios_loja ON bloqueios(loja_id,inicio,fim)')

    def lock(db):
        if c['DATABASE_URL']: db.execute('SELECT pg_advisory_xact_lock(?)',(7821601,))
        else: db.execute('BEGIN IMMEDIATE')

    def email_provedor():
        return os.environ.get('EMAIL_PROVIDER','brevo' if os.environ.get('BREVO_API_KEY') else 'resend').strip().lower()

    def email_pronto():
        provider=email_provedor()
        key='BREVO_API_KEY' if provider=='brevo' else 'RESEND_API_KEY' if provider=='resend' else None
        return bool(key and os.environ.get(key) and os.environ.get('EMAIL_FROM') and os.environ.get('PUBLIC_BASE_URL'))

    def conta(db,uid=None,email=None):
        column='id' if uid else 'email';value=uid or email
        row=db.execute(f'SELECT * FROM usuarios WHERE {column}=?',(value,)).fetchone()
        if row: return dict(row),'usuarios'
        row=db.execute(f'SELECT * FROM funcionarios WHERE {column}=? AND ativo=1',(value,)).fetchone()
        return (dict(row),'funcionarios') if row else (None,None)

    def registrar_aceite(db,uid):
        db.execute('INSERT INTO aceites(usuario_id,versao,aceito_em) VALUES(?,?,?) ON CONFLICT(usuario_id) DO UPDATE SET versao=excluded.versao,aceito_em=excluded.aceito_em',(uid,VERSAO_TERMOS,datetime.now(br).isoformat()))

    def email_confirmado(uid):
        with banco() as db:
            row,_=conta(db,uid=uid)
            return bool(row and db.execute('SELECT usuario_id FROM emails_confirmados WHERE usuario_id=? AND email=?',(uid,row['email'])).fetchone())

    def enviar_email(destino,subject,text,uid,acao):
        if email_provedor()=='brevo':
            name,address=parseaddr(os.environ['EMAIL_FROM'])
            payload={'sender':{'name':name or 'Grupo Havo','email':address},'to':[{'email':destino}],'subject':subject,'textContent':text}
            url='https://api.brevo.com/v3/smtp/email';authorization={'api-key':os.environ['BREVO_API_KEY']}
        else:
            payload={'from':os.environ['EMAIL_FROM'],'to':[destino],'subject':subject,'text':text}
            url='https://api.resend.com/emails';authorization={'Authorization':'Bearer '+os.environ['RESEND_API_KEY']}
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={**authorization,'Content-Type':'application/json','User-Agent':'BarberSaaS/2'})
        with urllib.request.urlopen(req,timeout=20) as response:
            if response.status not in (200,201,202): raise RuntimeError('Falha no envio de e-mail')

    def enviar_acao_email(uid,email,acao):
        raw=secrets.token_urlsafe(32);hashed=hashlib.sha256(raw.encode()).hexdigest()
        try:
            with banco() as db:
                lock(db)
                current,_=conta(db,uid=uid)
                if not current or current['email']!=email: return
                db.execute('DELETE FROM tokens_email WHERE usuario_id=? AND acao=?',(uid,acao))
                db.execute('INSERT INTO tokens_email(token,usuario_id,email,acao,expira) VALUES(?,?,?,?,?)',(hashed,uid,email,acao,int(time.time())+(1200 if acao=='senha' else 86400)))
            path='/redefinir-senha' if acao=='senha' else '/confirmar-email'
            link=os.environ['PUBLIC_BASE_URL'].rstrip('/')+path+'#'+raw
            subject='Redefina sua senha' if acao=='senha' else 'Confirme seu e-mail'
            text=f'{subject} no BarberSaaS: {link}\nEste link vale por '+('20 minutos.' if acao=='senha' else '24 horas.')+'\nSe você não solicitou, ignore esta mensagem. Não compartilhe o link.'
            c['enviar_email'](email,subject,text,uid,acao)
            status='enviado'
        except Exception:
            with banco() as db: db.execute('DELETE FROM tokens_email WHERE token=?',(hashed,))
            status='falhou'
        with banco() as db:
            db.execute('INSERT INTO eventos_email(id,usuario_id,acao,status,criado_em) VALUES(?,?,?,?,?)',(secrets.token_hex(16),uid,acao,status,datetime.now(br).isoformat()))

    @app.post('/api/conta/recuperar')
    def recuperar(data: EmailPedido,request: Request,background: BackgroundTasks):
        c['limitar'](request,'recuperar',5,900)
        if not email_pronto(): raise HTTPException(503,'O envio de e-mails está em configuração. Entre em contato com o suporte.')
        email=c['email_valido'](data.email)
        with banco() as db: row,_=conta(db,email=email)
        if row: background.add_task(enviar_acao_email,row['id'],email,'senha')
        return {'mensagem':'Se houver uma conta ativa para este e-mail, você receberá um link. Confira também o spam.'}

    @app.post('/api/conta/email/enviar')
    def reenviar(request: Request,background: BackgroundTasks):
        c['limitar'](request,'verificar-email',5,900)
        with banco() as db: user=usuario(request,db,True)
        if not email_pronto(): raise HTTPException(503,'O envio de e-mails está em configuração. Entre em contato com o suporte.')
        background.add_task(enviar_acao_email,user['id'],user['email'],'verificar')
        return {'mensagem':'Solicitação recebida. Confira seu e-mail e a pasta de spam.'}

    def validar_token(db,raw,acao):
        row=db.execute('SELECT * FROM tokens_email WHERE token=? AND acao=? AND expira>?',(hashlib.sha256(raw.encode()).hexdigest(),acao,int(time.time()))).fetchone()
        if not row: raise HTTPException(410,'Link inválido, expirado ou já utilizado. Solicite outro.')
        current,table=conta(db,uid=row['usuario_id'])
        if not current or current['email']!=row['email']: raise HTTPException(410,'Esta conta não está mais disponível.')
        return row,table

    @app.post('/api/conta/redefinir')
    def redefinir(data: NovaSenha,request: Request):
        c['limitar'](request,'nova-senha',20,900)
        with banco() as db:
            lock(db); row,table=validar_token(db,data.token,'senha')
            db.execute(f'UPDATE {table} SET senha=? WHERE id=?',(c['hash_senha'](data.senha),row['usuario_id']))
            db.execute('DELETE FROM sessoes WHERE usuario_id=?',(row['usuario_id'],))
            db.execute('DELETE FROM tokens_email WHERE usuario_id=?',(row['usuario_id'],))
        return {'mensagem':'Senha atualizada. Entre novamente com a nova senha.'}

    @app.post('/api/conta/email/confirmar')
    def confirmar_email(data: TokenPedido,request: Request):
        c['limitar'](request,'confirmar-email',20,900)
        with banco() as db:
            lock(db); row,_=validar_token(db,data.token,'verificar')
            db.execute('INSERT INTO emails_confirmados(usuario_id,email,confirmado_em) VALUES(?,?,?) ON CONFLICT(usuario_id) DO UPDATE SET email=excluded.email,confirmado_em=excluded.confirmado_em',(row['usuario_id'],row['email'],datetime.now(br).isoformat()))
            db.execute('DELETE FROM tokens_email WHERE token=?',(row['token'],))
        return {'mensagem':'E-mail confirmado com sucesso.'}

    def bloqueado(db,shop,barber,start,end):
        return bool(db.execute('SELECT id FROM bloqueios WHERE loja_id=? AND (barbeiro_id=? OR barbeiro_id=?) AND inicio<? AND fim>?',(shop,barber,'',end.isoformat(timespec='minutes'),start.isoformat(timespec='minutes'))).fetchone())

    @app.get('/api/bloqueios')
    def listar_bloqueios(request: Request):
        with banco() as db:
            user=dono(request,db)
            return [dict(r) for r in db.execute('SELECT * FROM bloqueios WHERE loja_id=? ORDER BY inicio',(user['loja_id'],)).fetchall()]

    @app.post('/api/bloqueios',status_code=201)
    def criar_bloqueio(data: Bloqueio,request: Request):
        if len(data.motivo.strip())<2: raise HTTPException(422,'Informe o motivo do bloqueio.')
        start=data.inicio.astimezone(br).replace(tzinfo=None) if data.inicio.tzinfo else data.inicio
        end=data.fim.astimezone(br).replace(tzinfo=None) if data.fim.tzinfo else data.fim
        start=start.replace(second=0,microsecond=0);end=end.replace(second=0,microsecond=0)
        if end<=start or end-start>timedelta(days=366) or end.replace(tzinfo=br)<=datetime.now(br): raise HTTPException(422,'Informe um período válido e futuro, de até 366 dias.')
        with banco() as db:
            if not c['DATABASE_URL']: db.execute('BEGIN IMMEDIATE')
            user=dono(request,db,True)
            if c['DATABASE_URL']: c['travar'](db,user['loja_id'],'')
            config=c['config_da_loja'](db,user['loja_id'])
            if data.barbeiro_id and not any(b['id']==data.barbeiro_id for b in config['barbeiros']): raise HTTPException(404,'Profissional não encontrado.')
            rows=db.execute("SELECT * FROM agendamentos WHERE loja_id=? AND status!='cancelado' AND inicio<?",(user['loja_id'],end.isoformat(timespec='minutes'))).fetchall()
            conflicts=[r for r in rows if (not data.barbeiro_id or r['barbeiro_id']==data.barbeiro_id) and datetime.fromisoformat(r['inicio'])+timedelta(minutes=r['duracao_minutos'])>start]
            if conflicts: raise HTTPException(409,'Há reservas nesse período. Reagende ou cancele esses atendimentos antes de bloquear.')
            id=secrets.token_hex(16)
            db.execute('INSERT INTO bloqueios(id,loja_id,barbeiro_id,inicio,fim,motivo) VALUES(?,?,?,?,?,?)',(id,user['loja_id'],data.barbeiro_id,start.isoformat(timespec='minutes'),end.isoformat(timespec='minutes'),data.motivo.strip()))
        return {'id':id}

    @app.post('/api/bloqueios/{id}/remover')
    def remover_bloqueio(id: str,request: Request):
        with banco() as db:
            user=dono(request,db,True)
            db.execute('DELETE FROM bloqueios WHERE id=? AND loja_id=?',(id,user['loja_id']))
        return {'status':'removido'}

    def criar_link_cliente(db,id):
        raw=secrets.token_urlsafe(32)
        db.execute('INSERT INTO links_clientes(reserva_id,token) VALUES(?,?) ON CONFLICT(reserva_id) DO UPDATE SET token=excluded.token',(id,hashlib.sha256(raw.encode()).hexdigest()))
        return '/minha-reserva#'+raw

    def reserva_cliente(db,token):
        row=db.execute('SELECT a.* FROM agendamentos a JOIN links_clientes l ON l.reserva_id=a.id WHERE l.token=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row: raise HTTPException(404,'Link de reserva inválido. Fale com a barbearia.')
        return dict(row)

    def futura(row):
        if row['status']!='agendado' or datetime.fromisoformat(row['inicio']).replace(tzinfo=br)<=datetime.now(br): raise HTTPException(409,'Este atendimento não pode mais ser alterado pelo link. Fale com a barbearia.')

    def dados_reserva(row):
        return {k:row[k] for k in ('id','cliente_nome','servico_nome','barbeiro_nome','inicio','preco','duracao_minutos','status')}

    @app.post('/api/cliente/reserva')
    def ler_reserva(data: TokenPedido,request: Request):
        c['limitar'](request,'ler-reserva',100)
        with banco() as db:
            row=reserva_cliente(db,data.token);config=c['config_da_loja'](db,row['loja_id'])
        return {**dados_reserva(row),'barbearia':config['nome'],'whatsapp':config['whatsapp']}

    @app.post('/api/cliente/horarios')
    def horarios_cliente(data: HorariosCliente,request: Request):
        c['limitar'](request,'horarios-cliente',100)
        with banco() as db:
            row=reserva_cliente(db,data.token);futura(row)
            c['exigir_assinatura'](db,row['loja_id'])
            config=c['config_da_loja'](db,row['loja_id'])
            if not any(b['id']==row['barbeiro_id'] for b in config['barbeiros']): raise HTTPException(409,'Fale com a barbearia para escolher outro profissional.')
            hours=[]
            for p in config['periodos']:
                cur=datetime.fromisoformat(f"{data.data}T{p['inicio']}");end=datetime.fromisoformat(f"{data.data}T{p['fim']}")
                while cur<end:
                    hour=cur.strftime('%H:%M')
                    try: start=c['inicio_valido'](config,data.data,hour,row['duracao_minutos'])
                    except HTTPException: cur+=timedelta(minutes=config['intervalo']);continue
                    if not c['ocupado'](db,row['loja_id'],row['barbeiro_id'],start,row['duracao_minutos'],row['id']): hours.append(hour)
                    cur+=timedelta(minutes=config['intervalo'])
        return {'horarios':hours}

    @app.post('/api/cliente/alterar')
    def alterar_cliente(data: AlteracaoCliente,request: Request,background: BackgroundTasks):
        c['limitar'](request,'alterar-cliente',30)
        if data.acao not in ('cancelar','reagendar'): raise HTTPException(422,'Ação inválida.')
        with banco() as db:
            if not c['DATABASE_URL']: db.execute('BEGIN IMMEDIATE')
            row=reserva_cliente(db,data.token)
            if c['DATABASE_URL']:
                c['travar'](db,row['loja_id'],row['barbeiro_id']);row=reserva_cliente(db,data.token)
            if data.acao=='cancelar' and row['status']=='cancelado': return {'status':'cancelado'}
            futura(row)
            if data.acao=='cancelar': db.execute("UPDATE agendamentos SET status='cancelado' WHERE id=?",(row['id'],))
            else:
                if not data.data or not data.horario: raise HTTPException(422,'Escolha a nova data e o horário.')
                c['exigir_assinatura'](db,row['loja_id'])
                config=c['config_da_loja'](db,row['loja_id'])
                if not any(b['id']==row['barbeiro_id'] for b in config['barbeiros']): raise HTTPException(409,'Fale com a barbearia para escolher outro profissional.')
                start=c['inicio_valido'](config,data.data,data.horario,row['duracao_minutos'])
                if c['ocupado'](db,row['loja_id'],row['barbeiro_id'],start,row['duracao_minutos'],row['id']): raise HTTPException(409,'Esse horário foi ocupado. Escolha outro.')
                db.execute('UPDATE agendamentos SET inicio=?,data_hora=? WHERE id=?',(start.isoformat(timespec='minutes'),f'{data.data} às {data.horario}',row['id']))
            updated=db.execute('SELECT * FROM agendamentos WHERE id=? AND loja_id=?',(row['id'],row['loja_id'])).fetchone()
            if data.acao=='cancelar' or updated['inicio']!=row['inicio']:
                c['notificar_evento'](db,updated,'cancelado' if data.acao=='cancelar' else 'reagendado')
        background.add_task(c['push_dispatch'])
        return {'status':'cancelado' if data.acao=='cancelar' else 'agendado'}

    @app.post('/api/agendamentos/{id}/link-cliente')
    def link_existente(id: int,request: Request):
        with banco() as db:
            user=dono(request,db,True)
            if not db.execute('SELECT id FROM agendamentos WHERE id=? AND loja_id=?',(id,user['loja_id'])).fetchone(): raise HTTPException(404,'Reserva não encontrada.')
            link=criar_link_cliente(db,id)
        return {'link':link}

    @app.get('/api/gestao/pagamentos')
    def historico(request: Request,offset: int=0):
        if offset<0 or offset>100000: raise HTTPException(422,'Página inválida.')
        with banco() as db:
            admin(request,db)
            return [dict(r) for r in db.execute('''SELECT p.*,l.slug,u.email AS confirmado_por_email FROM pagamentos p JOIN lojas l ON l.id=p.loja_id LEFT JOIN usuarios u ON u.id=p.confirmado_por ORDER BY p.confirmado_em DESC,p.id LIMIT 200 OFFSET ?''',(offset,)).fetchall()]

    def snapshot(db):
        if c['DATABASE_URL']: db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        else: db.execute('BEGIN')
        rows={table:[dict(r) for r in db.execute('SELECT '+','.join(columns)+' FROM '+table).fetchall()] for table,columns in TABLES.items()}
        return {'formato':'barbersaas-backup','versao':1,'criado_em':datetime.now(br).isoformat(),'tabelas':rows}

    def backup_payload():
        with banco() as db: return snapshot(db)

    @app.post('/api/gestao/backup')
    def backup(data: SenhaAtual,request: Request):
        c['limitar'](request,'backup',5,900)
        with banco() as db:
            user=admin(request,db,True)
            if not c['confere_senha'](data.senha,user['senha']): raise HTTPException(401,'Senha incorreta.')
        payload=backup_payload();raw=json.dumps(payload,ensure_ascii=False).encode()
        checksum=hashlib.sha256(raw).hexdigest()
        with banco() as db: db.execute('INSERT INTO copias(id,criado_em,administrador_id,checksum) VALUES(?,?,?,?)',(secrets.token_hex(16),payload['criado_em'],user['id'],checksum))
        return Response(raw,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="backup-barbersaas-{datetime.now(br).strftime("%Y%m%d-%H%M%S")}.json"','X-Backup-SHA256':checksum})

    @app.get('/api/gestao/operacao')
    def operacao(request: Request):
        with banco() as db:
            admin(request,db)
            last=db.execute('SELECT criado_em,checksum FROM copias ORDER BY criado_em DESC LIMIT 1').fetchone()
            failures=db.execute("SELECT COUNT(*) AS total FROM eventos_email WHERE status='falhou' AND criado_em>?",((datetime.now(br)-timedelta(days=1)).isoformat(),)).fetchone()['total']
        # A execução na nuvem é externa: este painel não consulta o status do GitHub.
        return {'email_configurado':email_pronto(),'falhas_email_24h':failures,'ultima_copia':dict(last) if last else None,'backup_automatico':None,'backup_provedor':'github_actions'}

    # Pontos de integração usados pelo núcleo e pelos testes de envio, sem expor tokens em respostas.
    c.update({'registrar_aceite':registrar_aceite,'email_pronto':email_pronto,'email_confirmado':email_confirmado,'enviar_acao_email':enviar_acao_email,'enviar_email':enviar_email,'bloqueado':bloqueado,'criar_link_cliente':criar_link_cliente,'backup_payload':backup_payload,'BACKUP_TABLES':TABLES})
