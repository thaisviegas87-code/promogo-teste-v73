from datetime import datetime
from pathlib import Path
import json
from app.main import SessionLocal, Base, engine, Promotora, Acao, Escala, Registro

# Recreate only the local test database.
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

db = SessionLocal()

proms = [
    ('Ana Clara Silva','PRO001','123456','OBA',1),
    ('Beatriz Ferreira','PRO002','123456','TOP',1),
    ('Carla Santos','PRO003','123456','OBA',1),
    ('Daniele Jesus','PRO004','123456','TOP',0),
    ('Fernanda Souza','PRO005','123456','OBA',1),
    ('Gabriela Silva','PRO006','123456','TOP',1),
    ('Juliana Lima','PRO007','123456','OBA',0),
    ('Letícia Carvalho','PRO008','123456','TOP',1),
]
P={}
for nome,codigo,senha,empresa,ativa in proms:
    p=Promotora(nome=nome,codigo=codigo,senha=senha,empresa=empresa,ativa=ativa)
    db.add(p); db.flush(); P[codigo]=p

acoes = [
    ('TESTE THAIS OBA','Cliente Teste Testando','OBA','2026-10-10','10h às 12h','Salvador - BA','Em andamento',['PRO001','PRO003']),
    ('Degustação Verão','Supermercado Bompreço','OBA','2026-10-10','10h às 16h','Salvador - BA','Em andamento',['PRO001','PRO005']),
    ('Lançamento Produto X','Shopping RioMar','TOP','2026-10-10','10h às 16h','Recife - PE','Em andamento',['PRO002','PRO006']),
    ('Ação Institucional','Moura Dubeux','OBA','2026-10-09','10h às 16h','Aracaju - SE','Concluída',['PRO003']),
    ('Sampling Verão','Parque Shopping','TOP','2026-10-09','10h às 16h','Brasília - DF','Em andamento',['PRO006','PRO008']),
    ('Festival da Cidade','Cliente Exemplo','OBA','2026-10-06','09h às 17h','Feira de Santana - BA','Pendente',['PRO005']),
    ('Ativação Black Friday','Shopping Recife','TOP','2026-10-15','10h às 18h','Recife - PE','Pendente',['PRO002','PRO008']),
    ('Experiência de Marca','Cliente Premium','OBA','2026-10-03','11h às 17h','Salvador - BA','Concluída',['PRO001','PRO003']),
    ('Campanha Universitária','Instituição Teste','TOP','2026-10-04','08h às 14h','Salvador - BA','Concluída',['PRO006']),
    ('Ação Cancelada Teste','Cliente Cancelado','TOP','2026-10-02','10h às 16h','Recife - PE','Cancelada',['PRO002']),
    ('Feira Regional','Cliente Regional','OBA','2026-10-11','09h às 15h','Vitória da Conquista - BA','Pendente',['PRO005']),
    ('Ativação Shopping','Shopping Teste','TOP','2026-10-12','10h às 18h','Recife - PE','Pendente',['PRO008']),
]
fields='abordagens,leads,brindes,observacoes,foto'
A={}
for i,(nome,cliente,empresa,data,horario,local,status,codigos) in enumerate(acoes,1):
    token = 'TESTE%03d'%i
    a=Acao(token=token,nome=nome,cliente=cliente,empresa=empresa,data=data,horario=horario,local=local,status=status,campos=fields)
    if 'Salvador' in local: a.latitude=-12.9777; a.longitude=-38.5016
    elif 'Recife' in local: a.latitude=-8.0476; a.longitude=-34.8770
    elif 'Aracaju' in local: a.latitude=-10.9472; a.longitude=-37.0731
    elif 'Brasília' in local: a.latitude=-15.7939; a.longitude=-47.8828
    elif 'Feira' in local: a.latitude=-12.2664; a.longitude=-38.9663
    else: a.latitude=-12.5; a.longitude=-40.0
    db.add(a); db.flush(); A[i]=a
    for codigo in codigos:
        db.add(Escala(acao_id=a.id,promotora_id=P[codigo].id))

def add_reg(acao_idx,codigo,tipo,dt,lat,lon,dados='',foto=None):
    db.add(Registro(acao_id=A[acao_idx].id,promotora_id=P[codigo].id,tipo=tipo,horario=datetime.fromisoformat(dt),latitude=lat,longitude=lon,dados=dados,foto=foto))

for idx,codigos in [(2,['PRO001','PRO005']),(3,['PRO002','PRO006']),(4,['PRO003']),(5,['PRO006','PRO008']),(8,['PRO001','PRO003']),(9,['PRO006'])]:
    for j,cod in enumerate(codigos):
        base=f'2026-10-{str(9 if idx in [4,5] else 4).zfill(2)}'
        lat=-12.9777; lon=-38.5016
        if idx==3: lat,lon=-8.0476,-34.8770
        if idx==4: lat,lon=-10.9472,-37.0731
        if idx==5: lat,lon=-15.7939,-47.8828
        if idx==9: lat,lon=-12.9777,-38.5016
        add_reg(idx,cod,'check-in',f'{base}T09:50:00',lat,lon,json.dumps({'precisao_m':'8 m'}))
        add_reg(idx,cod,'formulário',f'{base}T15:45:00',lat,lon,json.dumps({'abordagens':str(80+idx*7+j*10),'leads':str(12+idx+j),'brindes':str(40+idx*2),'observacoes':'Ação realizada conforme planejado.'},ensure_ascii=False),'/static/uploads/fake-photo.svg')
        if idx in [4,8,9]: add_reg(idx,cod,'check-out',f'{base}T16:05:00',lat,lon,json.dumps({'precisao_m':'10 m'}))

# A first test action has a check-in but no checkout, useful for testing "Em ação".
add_reg(1,'PRO001','check-in','2026-10-10T09:52:00',-12.9777,-38.5016,json.dumps({'precisao_m':'7 m'}))

db.commit(); db.close()
print('Banco fake criado:', len(proms), 'promotoras e', len(acoes), 'ações')
print('Login de teste: PRO001 / 123456')
print('Link de teste: http://127.0.0.1:8000/acao/TESTE001')
