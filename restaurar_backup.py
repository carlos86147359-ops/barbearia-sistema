"""Restaura uma cópia somente em um SQLite novo ou PostgreSQL vazio.

Não importa o aplicativo e não inicia migrações no banco em uso.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

spec=importlib.util.spec_from_file_location('backup_schema',Path(__file__).with_name('recursos.py'))
schema=importlib.util.module_from_spec(spec);spec.loader.exec_module(schema)
TABLES=schema.TABLES
from produtos import TABLES as PRODUCT_TABLES, DDL as PRODUCT_DDL, INDEXES as PRODUCT_INDEXES
INTEGER={'id':{'agendamentos'},'ativo':{'funcionarios'},'valor_centavos':{'pagamentos'},'reserva_id':{'links_clientes'},'duracao_minutos':{'agendamentos'},'comissao_pct':{'agendamentos'}}

def ler(path,checksum=None):
    raw=Path(path).read_bytes()
    if checksum and hashlib.sha256(raw).hexdigest()!=checksum.strip().lower(): raise ValueError('A soma de verificação não confere.')
    data=json.loads(raw)
    keys=set(data.get('tabelas',{}))
    allowed=[set(TABLES),set(TABLES)-{'cortesias'},set(TABLES)-set(PRODUCT_TABLES),set(TABLES)-set(PRODUCT_TABLES)-{'cortesias'}]
    allowed += [s-{'preferencias'} for s in allowed]
    if data.get('formato')!='barbersaas-backup' or data.get('versao')!=1 or keys not in allowed: raise ValueError('Formato de cópia não reconhecido.')
    tables=data['tabelas']
    tables.setdefault('cortesias',[])
    tables.setdefault('preferencias',[])
    for table in PRODUCT_TABLES: tables.setdefault(table,[])
    for table,columns in TABLES.items():
        if not isinstance(tables[table],list): raise ValueError('Tabela inválida: '+table)
        for row in tables[table]:
            if not isinstance(row,dict) or set(row)!=set(columns): raise ValueError('Colunas inválidas: '+table)
            if any(not isinstance(v,(str,int,float,type(None))) for v in row.values()): raise ValueError('Valor inválido: '+table)
    shops={r['id'] for r in tables['lojas']};users={r['id'] for r in tables['usuarios']}|{r['id'] for r in tables['funcionarios']};reservations={r['id'] for r in tables['agendamentos']}
    accounts={'dono:'+r['id'] for r in tables['usuarios']}|{'barbeiro:'+r['id'] for r in tables['funcionarios']}
    if any(r['id'] not in accounts or r['tema'] not in ('claro','escuro','sistema') for r in tables['preferencias']): raise ValueError('Preferência inválida ou conta ausente.')
    for table in ('usuarios','funcionarios','assinaturas','pagamentos','agendamentos','bloqueios','cortesias'):
        if any(r['loja_id'] not in shops for r in tables[table]): raise ValueError('Barbearia ausente em '+table)
    for table in ('emails_confirmados','aceites'):
        if any(r['usuario_id'] not in users for r in tables[table]): raise ValueError('Conta ausente em '+table)
    if any(r['reserva_id'] not in reservations for r in tables['links_clientes']): raise ValueError('Reserva ausente no link privado.')
    for table in PRODUCT_TABLES:
        if any(r['loja_id'] not in shops for r in tables[table]): raise ValueError('Barbearia ausente em '+table)
    products={(r['loja_id'],r['id']) for r in tables['produtos']}
    variants={(r['loja_id'],r['id']):r['produto_id'] for r in tables['variantes_produto']}
    sales={(r['loja_id'],r['id']) for r in tables['vendas_produtos']}
    staff={(r['loja_id'],r['id']) for r in tables['funcionarios']}
    for table in ('variantes_produto','itens_venda','movimentacoes_estoque'):
        for row in tables[table]:
            if (row['loja_id'],row['produto_id']) not in products: raise ValueError('Produto ausente em '+table)
            if table!='variantes_produto' and variants.get((row['loja_id'],row['variante_id']))!=row['produto_id']: raise ValueError('Variante incompatível em '+table)
            if table!='variantes_produto' and row['venda_id'] is not None and (row['loja_id'],row['venda_id']) not in sales: raise ValueError('Venda ausente em '+table)
    if any((r['loja_id'],r['funcionario_id']) not in staff for r in tables['permissoes_caixa']): raise ValueError('Profissional ausente nas permissões.')
    return tables

def restaurar(tables,sqlite_path=None,postgres=False):
    if postgres:
        import psycopg
        dsn=os.environ.get('RESTORE_DATABASE_URL')
        if not dsn: raise ValueError('Configure RESTORE_DATABASE_URL para o banco novo.')
        db=psycopg.connect(dsn,connect_timeout=15);placeholder='%s'
    else:
        target=Path(sqlite_path)
        # Criação exclusiva impede sobrescrever qualquer arquivo existente.
        with target.open('xb'): pass
        db=sqlite3.connect(target);placeholder='?'
    try:
        if postgres:
            existing=db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'").fetchall()
            if existing: raise ValueError('O banco de destino deve estar vazio, sem tabelas. O banco em uso nunca deve ser usado como destino.')
        for table,columns in TABLES.items():
            definitions=[]
            for col in columns:
                typ='BIGINT' if table in INTEGER.get(col,set()) else 'REAL' if col=='preco' else 'TEXT'
                if table=='agendamentos' and col=='id': typ='BIGSERIAL' if postgres else 'INTEGER'
                primary=col=='id' or (table in ('assinaturas','cortesias') and col=='loja_id') or (table in ('aceites','emails_confirmados') and col=='usuario_id') or (table=='links_clientes' and col=='reserva_id')
                definitions.append(col+' '+typ+(' PRIMARY KEY' if primary else '')+(' UNIQUE' if (table,col) in {('lojas','slug'),('usuarios','email'),('usuarios','loja_id'),('funcionarios','email'),('pagamentos','referencia'),('links_clientes','token')} else ''))
            if table=='funcionarios': definitions.append('UNIQUE(loja_id,barbeiro_id)')
            db.execute('CREATE TABLE '+table+' ('+(PRODUCT_DDL[table] if table in PRODUCT_DDL else ','.join(definitions))+')')
            sql='INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join([placeholder]*len(columns))+')'
            for row in tables[table]: db.execute(sql,tuple(row[col] for col in columns))
        for sql in PRODUCT_INDEXES: db.execute(sql)
        if postgres:
            db.execute("SELECT setval(pg_get_serial_sequence('agendamentos','id'),COALESCE((SELECT MAX(id) FROM agendamentos),1),(SELECT COUNT(*)>0 FROM agendamentos))")
        for table in TABLES:
            count=db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            if count!=len(tables[table]): raise ValueError('Quantidade divergente: '+table)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally: db.close()
    return {table:len(rows) for table,rows in tables.items()}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arquivo');parser.add_argument('--sha256',help='Soma do arquivo .sha256 salvo junto da cópia')
    choice=parser.add_mutually_exclusive_group();choice.add_argument('--sqlite-novo');choice.add_argument('--postgres-vazio',action='store_true')
    args=parser.parse_args()
    try:
        tables=ler(args.arquivo,args.sha256)
        if args.sqlite_novo or args.postgres_vazio: print('Restauração validada:',restaurar(tables,args.sqlite_novo,args.postgres_vazio))
        else: print('Estrutura validada. Nenhum banco alterado.',{k:len(v) for k,v in tables.items()})
    except Exception as exc: raise SystemExit('Restauração interrompida: '+str(exc))
