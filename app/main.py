from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey, text, inspect
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, joinedload
from datetime import datetime
from pathlib import Path
import secrets, shutil, json, re, calendar, os, hashlib, hmac, base64

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / 'static' / 'uploads'
UPLOADS.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if DATABASE_URL:
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len('postgres://'):]
    elif DATABASE_URL.startswith('postgresql://'):
        DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len('postgresql://'):]
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    DB = BASE / 'oba.db'
    engine = create_engine(f'sqlite:///{DB}', connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

class Promotora(Base):
    __tablename__ = 'promotoras'
    id = Column(Integer, primary_key=True)
    nome = Column(String(120), nullable=False)
    codigo = Column(String(30), unique=True, nullable=False)
    senha = Column(String(100), nullable=False)
    empresa = Column(String(20), nullable=False, default='OBA')
    ativa = Column(Integer, default=1)

class Cliente(Base):
    __tablename__ = 'clientes'
    id = Column(Integer, primary_key=True)
    nome = Column(String(160), nullable=False)
    ativo = Column(Integer, default=1)

class Usuario(Base):
    __tablename__ = 'usuarios'
    id = Column(Integer, primary_key=True)
    nome = Column(String(120), nullable=False)
    usuario = Column(String(80), unique=True, nullable=False)
    senha = Column(String(100), nullable=False)
    ativo = Column(Integer, default=1)
    perfil = Column(String(30), nullable=False, default='Administrador')
    cliente_id = Column(Integer, ForeignKey('clientes.id'), nullable=True)

class Acao(Base):
    __tablename__ = 'acoes'
    id = Column(Integer, primary_key=True)
    token = Column(String(30), unique=True, nullable=False)
    nome = Column(String(160), nullable=False)
    cliente = Column(String(160), nullable=False)
    empresa = Column(String(20), nullable=False, default='OBA')
    data = Column(String(20), nullable=False)
    horario = Column(String(50), nullable=False)
    local = Column(String(250), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    campos = Column(Text, default='')
    status = Column(String(30), nullable=False, default='Pendente')
    criada_em = Column(DateTime, default=datetime.now)
    cidade = Column(String(100), nullable=True)
    brindes_disponiveis = Column(Integer, default=0)

class Escala(Base):
    __tablename__ = 'escalas'
    id = Column(Integer, primary_key=True)
    acao_id = Column(Integer, ForeignKey('acoes.id'), nullable=False)
    promotora_id = Column(Integer, ForeignKey('promotoras.id'), nullable=False)
    acao = relationship('Acao')
    promotora = relationship('Promotora')

class Registro(Base):
    __tablename__ = 'registros'
    id = Column(Integer, primary_key=True)
    acao_id = Column(Integer, ForeignKey('acoes.id'), nullable=False)
    promotora_id = Column(Integer, ForeignKey('promotoras.id'), nullable=False)
    tipo = Column(String(30), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    horario = Column(DateTime, default=datetime.now)
    dados = Column(Text, default='')
    foto = Column(String(300), nullable=True)
    promotora = relationship('Promotora')

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 310000)
    return 'pbkdf2_sha256$310000$' + base64.urlsafe_b64encode(salt).decode() + '$' + base64.urlsafe_b64encode(digest).decode()

def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    if not stored.startswith('pbkdf2_sha256$'):
        return hmac.compare_digest(password, stored)
    try:
        _, rounds, salt_b64, digest_b64 = stored.split('$', 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

Base.metadata.create_all(engine)

# Migração compatível com SQLite/PostgreSQL.
with engine.begin() as conn:
    insp = inspect(conn)
    pcols = {c['name'] for c in insp.get_columns('promotoras')}
    if 'empresa' not in pcols:
        conn.execute(text("ALTER TABLE promotoras ADD COLUMN empresa VARCHAR(20) NOT NULL DEFAULT 'OBA'"))
    acols = {c['name'] for c in insp.get_columns('acoes')}
    if 'empresa' not in acols:
        conn.execute(text("ALTER TABLE acoes ADD COLUMN empresa VARCHAR(20) NOT NULL DEFAULT 'OBA'"))
    if 'status' not in acols:
        conn.execute(text("ALTER TABLE acoes ADD COLUMN status VARCHAR(30) NOT NULL DEFAULT 'Pendente'"))
    if 'cidade' not in acols:
        conn.execute(text("ALTER TABLE acoes ADD COLUMN cidade VARCHAR(100)"))
    if 'brindes_disponiveis' not in acols:
        conn.execute(text("ALTER TABLE acoes ADD COLUMN brindes_disponiveis INTEGER NOT NULL DEFAULT 0"))
    ucols = {c['name'] for c in insp.get_columns('usuarios')}
    if 'cliente_id' not in ucols:
        conn.execute(text("ALTER TABLE usuarios ADD COLUMN cliente_id INTEGER"))

app = FastAPI(title='PromoGo')
app.mount('/static', StaticFiles(directory=BASE/'static'), name='static')
templates = Jinja2Templates(directory=BASE/'templates')

PUBLIC_PREFIXES = ('/login', '/acao/', '/static/')

@app.middleware('http')
async def admin_guard(request: Request, call_next):
    path = request.url.path
    if path == '/' or path.startswith('/admin') or path in ('/acoes','/promotoras','/relatorios'):
        if not admin_autenticado(request):
            return RedirectResponse('/login', status_code=303)
    response = await call_next(request)
    return response

# SessionMiddleware fica por fora do guard para que request.session esteja disponível nele.
app.add_middleware(SessionMiddleware, secret_key=os.getenv('PROMOGO_SECRET_KEY', 'promogo-demo-chave-local'), max_age=60*60*12, https_only=os.getenv('PROMOGO_HTTPS_ONLY','false').lower()=='true', same_site='lax')

def admin_autenticado(request: Request):
    return bool(request.session.get('admin_user_id'))


def usuario_atual(request: Request):
    uid = request.session.get('admin_user_id')
    if not uid:
        return None
    db = SessionLocal()
    u = db.get(Usuario, uid)
    db.close()
    return u


CAMPOS = {
    'abordagens': ('Pessoas abordadas', 'Número'),
    'leads': ('Leads captados', 'Número'),
    'brindes': ('Brindes entregues', 'Número'),
    'participantes': ('Participantes da ativação', 'Número'),
    'perguntas_produto': ('Perguntas sobre produto/serviço', 'Número'),
    'duvidas_gerais': ('Dúvidas gerais', 'Número'),
    'observacoes': ('Observações', 'Texto'),
    'foto': ('Foto da ação', 'Foto'),
}
STATUS_ACAO = ['Em andamento', 'Concluída', 'Pendente', 'Cancelada']

def split_fields(value): return [x for x in (value or '').split(',') if x]
def field_label(key): return CAMPOS.get(key, (key, ''))[0]
templates.env.globals['field_label'] = field_label

def save_photo(photo: UploadFile | None):
    if not photo or not photo.filename: return None
    ext = Path(photo.filename).suffix.lower() or '.jpg'
    name = f'{secrets.token_hex(10)}{ext}'
    path = UPLOADS / name
    with path.open('wb') as f: shutil.copyfileobj(photo.file, f)
    return f'/static/uploads/{name}'

def make_token(db):
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        token = ''.join(secrets.choice(alphabet) for _ in range(10))
        if not db.query(Acao).filter_by(token=token).first(): return token

def map_url(lat, lon):
    if lat is None or lon is None: return None
    return f'https://www.google.com/maps?q={lat},{lon}'

def get_json(value):
    try: return json.loads(value or '{}')
    except Exception: return {}

def aggregate_formularios(registros):
    totals = {'abordagens': 0, 'leads': 0, 'brindes': 0, 'participantes': 0, 'perguntas_produto': 0, 'duvidas_gerais': 0}
    por_promotora = {}
    por_acao = {}
    formularios = 0
    for r in registros:
        if r.tipo != 'formulário':
            continue
        formularios += 1
        dados = get_json(r.dados)
        bucket = por_promotora.setdefault(r.promotora_id, {'abordagens':0,'leads':0,'brindes':0,'participantes':0,'perguntas_produto':0,'duvidas_gerais':0})
        abucket = por_acao.setdefault(r.acao_id, {'abordagens':0,'leads':0,'brindes':0,'participantes':0,'perguntas_produto':0,'duvidas_gerais':0})
        for key in totals:
            try: val = int(float(str(dados.get(key, '')).replace(',', '.')))
            except Exception: val = 0
            totals[key] += val
            bucket[key] += val
            abucket[key] += val
    return totals, formularios, por_promotora, por_acao

def action_status(db, acao_id, promotora_id):
    checkin = db.query(Registro).filter_by(acao_id=acao_id, promotora_id=promotora_id, tipo='check-in').order_by(Registro.horario.desc()).first()
    checkout = db.query(Registro).filter_by(acao_id=acao_id, promotora_id=promotora_id, tipo='check-out').order_by(Registro.horario.desc()).first()
    if not checkin: return 'Aguardando', checkin, checkout
    if checkout and checkout.horario >= checkin.horario: return 'Finalizada', checkin, checkout
    return 'Em ação', checkin, checkout

def parse_end_time(horario):
    m = re.search(r'(?:às|a|-) ?(\d{1,2})(?:h|:)?(\d{2})?', horario or '', re.I)
    if not m:
        nums = re.findall(r'\d{1,2}', horario or '')
        if not nums: return ''
        h = int(nums[-1]); minute = 0
    else:
        h = int(m.group(1)); minute = int(m.group(2) or 0)
    return f'{h:02d}:{minute:02d}' if h <= 23 else ''

def status_classes(status):
    return {
        'Em andamento': 'status-green', 'Concluída': 'status-orange',
        'Pendente': 'status-red', 'Cancelada': 'status-gray',
        'Ativa': 'status-green', 'Inativa': 'status-red',
        'Em ação': 'status-green', 'Finalizada': 'status-orange', 'Aguardando': 'status-gray'
    }.get(status, 'status-gray')

def initials(name):
    parts = [p for p in (name or '').split() if p]
    return ''.join(p[0] for p in parts[:2]).upper() or '?'

templates.env.globals.update(map_url=map_url, get_json=get_json, status_classes=status_classes, initials=initials)

def seed_demo_data():
    if os.getenv('PROMOGO_SEED_DEMO','').lower() not in ('1','true','yes'):
        return
    with SessionLocal() as db:
        if db.query(Cliente).count() == 0:
            db.add(Cliente(nome='Cliente Teste Testando', ativo=1)); db.flush()
        cliente_demo=db.query(Cliente).filter_by(nome='Cliente Teste Testando').first()
        if db.query(Usuario).count() == 0:
            db.add(Usuario(nome='Administrador', usuario='admin', senha=hash_password('123456'), perfil='Administrador', ativo=1))
        else:
            u=db.query(Usuario).filter_by(usuario='admin').first()
            if not u:
                db.add(Usuario(nome='Administrador', usuario='admin', senha=hash_password('123456'), perfil='Administrador', ativo=1))
        if not db.query(Usuario).filter_by(usuario='cliente_demo').first():
            db.add(Usuario(nome='Cliente Demonstração', usuario='cliente_demo', senha=hash_password('123456'), perfil='Cliente', ativo=1, cliente_id=cliente_demo.id))
        db.flush()
        if db.query(Acao).count() > 0:
            db.commit()
            return
        proms = [
            ('Ana Clara Silva','PRO001','123456','OBA',1),('Beatriz Ferreira','PRO002','123456','TOP',1),
            ('Carla Santos','PRO003','123456','OBA',1),('Daniele Jesus','PRO004','123456','TOP',0),
            ('Fernanda Souza','PRO005','123456','OBA',1),('Gabriela Silva','PRO006','123456','TOP',1),
            ('Juliana Lima','PRO007','123456','OBA',0),('Letícia Carvalho','PRO008','123456','TOP',1)]
        P={}
        for nome,codigo,senha,empresa,ativa in proms:
            p=Promotora(nome=nome,codigo=codigo,senha=hash_password(senha),empresa=empresa,ativa=ativa); db.add(p); db.flush(); P[codigo]=p
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
            ('Ativação Shopping','Shopping Teste','TOP','2026-10-12','10h às 18h','Recife - PE','Pendente',['PRO008'])]
        fields='abordagens,leads,brindes,perguntas_produto,duvidas_gerais,observacoes,foto'; A={}
        for i,(nome,cliente,empresa,data,horario,local,status,codigos) in enumerate(acoes,1):
            cidade = local.split(' - ')[0] if ' - ' in local else local
            a=Acao(token=f'TESTE{i:03d}',nome=nome,cliente=cliente,empresa=empresa,data=data,horario=horario,local=local,cidade=cidade,status=status,campos=fields,brindes_disponiveis=500)
            coords={'Salvador':(-12.9777,-38.5016),'Recife':(-8.0476,-34.8770),'Aracaju':(-10.9472,-37.0731),'Brasília':(-15.7939,-47.8828),'Feira':(-12.2664,-38.9663)}
            a.latitude,a.longitude=next((v for k,v in coords.items() if k in local),(-12.5,-40.0)); db.add(a); db.flush(); A[i]=a
            for codigo in codigos: db.add(Escala(acao_id=a.id,promotora_id=P[codigo].id))
        def add_reg(acao_idx,codigo,tipo,dt,lat,lon,dados='',foto=None):
            db.add(Registro(acao_id=A[acao_idx].id,promotora_id=P[codigo].id,tipo=tipo,horario=datetime.fromisoformat(dt),latitude=lat,longitude=lon,dados=dados,foto=foto))
        for idx,codigos in [(2,['PRO001','PRO005']),(3,['PRO002','PRO006']),(4,['PRO003']),(5,['PRO006','PRO008']),(8,['PRO001','PRO003']),(9,['PRO006'])]:
            for j,cod in enumerate(codigos):
                base=f'2026-10-{str(9 if idx in [4,5] else 4).zfill(2)}'; lat,lon=-12.9777,-38.5016
                if idx==3: lat,lon=-8.0476,-34.8770
                if idx==4: lat,lon=-10.9472,-37.0731
                if idx==5: lat,lon=-15.7939,-47.8828
                add_reg(idx,cod,'check-in',f'{base}T09:50:00',lat,lon,json.dumps({'precisao_m':'8 m'}))
                add_reg(idx,cod,'formulário',f'{base}T15:45:00',lat,lon,json.dumps({'abordagens':str(80+idx*7+j*10),'leads':str(12+idx+j),'brindes':str(40+idx*2),'perguntas_produto':str(18+idx+j),'duvidas_gerais':str(9+j),'observacoes':'Ação realizada conforme planejado.'},ensure_ascii=False),'/static/uploads/fake-photo.svg')
                if idx in [4,8,9]: add_reg(idx,cod,'check-out',f'{base}T16:05:00',lat,lon,json.dumps({'precisao_m':'10 m'}))
        add_reg(1,'PRO001','check-in','2026-10-10T09:52:00',-12.9777,-38.5016,json.dumps({'precisao_m':'7 m'}))
        db.commit()

if os.getenv('PROMOGO_SEED_DEMO','').lower() in ('1','true','yes'):
    with SessionLocal() as _db:
        for _a in _db.query(Acao).all():
            if not _a.cidade and _a.local:
                _a.cidade = _a.local.split(' - ')[0]
            if not (_a.brindes_disponiveis or 0):
                _a.brindes_disponiveis = 500
            current = set(split_fields(_a.campos))
            current.update(('perguntas_produto','duvidas_gerais'))
            _a.campos = ','.join([k for k in ('abordagens','leads','brindes','participantes','perguntas_produto','duvidas_gerais','observacoes','foto') if k in current])
        _db.commit()

seed_demo_data()

def counts(db):
    return {
        'acoes': db.query(Acao).count(),
        'acoes_andamento': db.query(Acao).filter_by(status='Em andamento').count(),
        'promotoras': db.query(Promotora).count(),
        'ativas': db.query(Promotora).filter_by(ativa=1).count(),
        'inativas': db.query(Promotora).filter_by(ativa=0).count(),
        'checkins': db.query(Registro).filter_by(tipo='check-in').count(),
        'checkouts': db.query(Registro).filter_by(tipo='check-out').count(),
        'fotos': db.query(Registro).filter(Registro.foto.isnot(None)).count(),
        'oba': db.query(Acao).filter_by(empresa='OBA').count(),
        'top': db.query(Acao).filter_by(empresa='TOP').count(),
    }

@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    if admin_autenticado(request):
        return RedirectResponse('/', status_code=303)
    return templates.TemplateResponse(request=request, name='admin_login.html', context={'request':request})

@app.post('/login', response_class=HTMLResponse)
def login_admin(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    db = SessionLocal()
    u = db.query(Usuario).filter_by(usuario=usuario.strip(), ativo=1).first()
    if u and not verify_password(senha, u.senha):
        u = None
    if not u:
        db.close()
        return templates.TemplateResponse(request=request, name='admin_login.html', context={'request':request,'erro':'Usuário ou senha inválidos.'})
    request.session['admin_user_id'] = u.id
    db.close()
    return RedirectResponse('/', status_code=303)

@app.get('/logout')
def logout(request: Request):
    request.session.pop('admin_user_id', None)
    return RedirectResponse('/login', status_code=303)

@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    db = SessionLocal(); stats = counts(db)
    acoes = db.query(Acao).order_by(Acao.data.desc(), Acao.id.desc()).all()
    recentes = acoes[:4]
    status_counts = {s: db.query(Acao).filter_by(status=s).count() for s in STATUS_ACAO}
    prom = db.query(Promotora).order_by(Promotora.nome).all()
    db.close()
    map_points=[{'lat':a.latitude,'lon':a.longitude,'nome':a.nome,'empresa':a.empresa,'local':a.local,'id':a.id} for a in acoes if a.latitude is not None and a.longitude is not None]
    return templates.TemplateResponse(request=request, name='home.html', context={'request':request,'stats':stats,'acoes':acoes,'recentes':recentes,'promotoras':prom,'status_counts':status_counts,'map_points':map_points})

@app.get('/admin/promotora/nova', response_class=HTMLResponse)
def nova_promotora_page(request: Request):
    return templates.TemplateResponse(request=request, name='nova_promotora.html', context={'request':request})

@app.get('/admin/acao/nova', response_class=HTMLResponse)
def nova_acao_page(request: Request):
    db=SessionLocal(); prom=db.query(Promotora).filter_by(ativa=1).order_by(Promotora.nome).all(); db.close()
    return templates.TemplateResponse(request=request, name='nova_acao.html', context={'request':request,'promotoras':prom,'status_options':STATUS_ACAO})

@app.post('/admin/promotora')
def criar_promotora(nome:str=Form(...), codigo:str=Form(...), senha:str=Form(...), empresa:str=Form('OBA')):
    db=SessionLocal(); codigo=codigo.strip().upper(); empresa=empresa.upper() if empresa.upper() in ('OBA','TOP') else 'OBA'
    if db.query(Promotora).filter_by(codigo=codigo).first(): db.close(); return RedirectResponse('/promotoras?erro=O+código+já+existe',303)
    db.add(Promotora(nome=nome.strip(),codigo=codigo.upper(),senha=hash_password(senha),empresa=empresa)); db.commit(); db.close()
    return RedirectResponse('/promotoras',303)

@app.get('/promotoras', response_class=HTMLResponse)
def promotoras(request: Request, busca:str='', status:str='', empresa:str='', ordem:str='nome'):
    db=SessionLocal(); q=db.query(Promotora)
    if busca:
        like=f'%{busca.strip()}%'; q=q.filter((Promotora.nome.ilike(like)) | (Promotora.codigo.ilike(like)) | (Promotora.empresa.ilike(like)))
    if status=='ativa': q=q.filter_by(ativa=1)
    elif status=='inativa': q=q.filter_by(ativa=0)
    if empresa in ('OBA','TOP'): q=q.filter_by(empresa=empresa)
    q=q.order_by(Promotora.nome.desc() if ordem=='nome_desc' else Promotora.codigo if ordem=='codigo' else Promotora.nome)
    items=q.all(); total=db.query(Promotora).count(); ativas=db.query(Promotora).filter_by(ativa=1).count(); inativas=total-ativas
    db.close()
    return templates.TemplateResponse(request=request,name='promotoras.html',context={'request':request,'promotoras':items,'busca':busca,'status':status,'empresa':empresa,'ordem':ordem,'total':total,'ativas':ativas,'inativas':inativas,'novas':min(3,total)})

@app.post('/admin/promotora/{promotora_id}/toggle')
def toggle_promotora(promotora_id:int):
    db=SessionLocal(); p=db.get(Promotora,promotora_id)
    if p: p.ativa=0 if p.ativa else 1; db.commit()
    db.close(); return RedirectResponse('/promotoras',303)

@app.get('/admin/promotora/{promotora_id}/editar', response_class=HTMLResponse)
def editar_promotora_page(request:Request,promotora_id:int):
    db=SessionLocal(); p=db.get(Promotora,promotora_id); db.close()
    if not p: return HTMLResponse('Promotora não encontrada',404)
    return templates.TemplateResponse(request=request,name='editar_promotora.html',context={'request':request,'promotora':p})

@app.post('/admin/promotora/{promotora_id}/editar')
def editar_promotora(promotora_id:int,nome:str=Form(...),codigo:str=Form(...),senha:str=Form(''),empresa:str=Form('OBA')):
    db=SessionLocal(); p=db.get(Promotora,promotora_id)
    if not p: db.close(); return HTMLResponse('Promotora não encontrada',404)
    codigo=codigo.strip().upper(); empresa=empresa.upper() if empresa.upper() in ('OBA','TOP') else 'OBA'
    conflito=db.query(Promotora).filter(Promotora.codigo==codigo,Promotora.id!=promotora_id).first()
    if conflito: db.close(); return RedirectResponse(f'/admin/promotora/{promotora_id}/editar?erro=codigo',303)
    p.nome=nome.strip(); p.codigo=codigo; p.empresa=empresa
    if senha.strip(): p.senha=hash_password(senha.strip())
    db.commit(); db.close(); return RedirectResponse('/promotoras',303)

@app.post('/admin/promotora/{promotora_id}/reset-senha')
def reset_senha(promotora_id:int,senha:str=Form(...)):
    db=SessionLocal(); p=db.get(Promotora,promotora_id)
    if p: p.senha=hash_password(senha.strip()); db.commit()
    db.close(); return RedirectResponse(f'/admin/promotora/{promotora_id}/editar?ok=senha',303)

@app.post('/admin/acao')
def criar_acao(nome:str=Form(...),cliente:str=Form(...),empresa:str=Form('OBA'),data:str=Form(...),horario:str=Form(...),local:str=Form(...),cidade:str=Form(''),brindes_disponiveis:int=Form(0),latitude:str=Form(''),longitude:str=Form(''),status:str=Form('Pendente'),campos:list[str]=Form([]),promotoras:list[int]=Form([])):
    db=SessionLocal(); empresa=empresa.upper() if empresa.upper() in ('OBA','TOP') else 'OBA'; status=status if status in STATUS_ACAO else 'Pendente'
    acao=Acao(token=make_token(db),nome=nome.strip(),cliente=cliente.strip(),empresa=empresa,data=data,horario=horario,local=local.strip(),latitude=float(latitude) if latitude else None,longitude=float(longitude) if longitude else None,campos=','.join(campos),status=status)
    db.add(acao); db.commit(); db.refresh(acao)
    for pid in promotoras:
        if db.get(Promotora,pid): db.add(Escala(acao_id=acao.id,promotora_id=pid))
    db.commit(); aid=acao.id; db.close(); return RedirectResponse(f'/admin/acao/{aid}',303)

@app.get('/admin/acao/{acao_id}/editar', response_class=HTMLResponse)
def editar_acao_page(request:Request,acao_id:int):
    db=SessionLocal(); acao=db.get(Acao,acao_id)
    if not acao: db.close(); return HTMLResponse('Ação não encontrada',404)
    prom=db.query(Promotora).filter_by(ativa=1).order_by(Promotora.nome).all(); escalas={e.promotora_id for e in db.query(Escala).filter_by(acao_id=acao_id).all()}; db.close()
    return templates.TemplateResponse(request=request,name='editar_acao.html',context={'request':request,'acao':acao,'promotoras':prom,'escaladas':escalas,'selected':split_fields(acao.campos),'status_options':STATUS_ACAO})

@app.post('/admin/acao/{acao_id}/editar')
def editar_acao(acao_id:int,nome:str=Form(...),cliente:str=Form(...),empresa:str=Form('OBA'),data:str=Form(...),horario:str=Form(...),local:str=Form(...),cidade:str=Form(''),brindes_disponiveis:int=Form(0),latitude:str=Form(''),longitude:str=Form(''),status:str=Form('Pendente'),campos:list[str]=Form([]),promotoras:list[int]=Form([]),gerar_novo_link:str=Form('')):
    db=SessionLocal(); acao=db.get(Acao,acao_id)
    if not acao: db.close(); return HTMLResponse('Ação não encontrada',404)
    acao.nome=nome.strip(); acao.cliente=cliente.strip(); acao.empresa=empresa.upper() if empresa.upper() in ('OBA','TOP') else 'OBA'; acao.data=data; acao.horario=horario; acao.local=local.strip(); acao.cidade=cidade.strip(); acao.brindes_disponiveis=brindes_disponiveis; acao.latitude=float(latitude) if latitude else None; acao.longitude=float(longitude) if longitude else None; acao.status=status if status in STATUS_ACAO else 'Pendente'; acao.campos=','.join(campos)
    if gerar_novo_link: acao.token=make_token(db)
    db.query(Escala).filter_by(acao_id=acao_id).delete(synchronize_session=False)
    for pid in promotoras:
        if db.get(Promotora,pid): db.add(Escala(acao_id=acao_id,promotora_id=pid))
    db.commit(); db.close(); return RedirectResponse(f'/admin/acao/{acao_id}',303)

@app.get('/acoes', response_class=HTMLResponse)
def acoes(request:Request,empresa:str='',promotora_id:int=0,status:str='',data_inicio:str='',data_fim:str=''):
    db=SessionLocal(); q=db.query(Acao)
    if empresa in ('OBA','TOP'): q=q.filter_by(empresa=empresa)
    if status in STATUS_ACAO: q=q.filter_by(status=status)
    if data_inicio: q=q.filter(Acao.data>=data_inicio)
    if data_fim: q=q.filter(Acao.data<=data_fim)
    if promotora_id: q=q.join(Escala).filter(Escala.promotora_id==promotora_id)
    items=q.order_by(Acao.data.desc(),Acao.id.desc()).all(); prom=db.query(Promotora).order_by(Promotora.nome).all(); db.close()
    return templates.TemplateResponse(request=request,name='acoes.html',context={'request':request,'acoes':items,'promotoras':prom,'empresa':empresa,'promotora_id':promotora_id,'status':status,'data_inicio':data_inicio,'data_fim':data_fim,'status_options':STATUS_ACAO})

@app.get('/relatorios', response_class=HTMLResponse)
def relatorios(request:Request,empresa:str='',promotora_id:int=0,acao_id:int=0,mes:str='',cidade:str='',data_inicio:str='',data_fim:str=''):
    db=SessionLocal(); q=db.query(Registro).options(joinedload(Registro.promotora)).join(Acao,Registro.acao_id==Acao.id)
    if empresa in ('OBA','TOP'): q=q.filter(Acao.empresa==empresa)
    if promotora_id: q=q.filter(Registro.promotora_id==promotora_id)
    if acao_id: q=q.filter(Registro.acao_id==acao_id)
    # Nos relatórios, os filtros de período devem considerar quando o registro
    # foi enviado, e não a data cadastrada para a ação.
    if mes:
        q = q.filter(Registro.horario >= f'{mes}-01')
        try:
            ano, numero_mes = map(int, mes.split('-'))
            if numero_mes == 12:
                proximo_mes = f'{ano + 1}-01-01'
            else:
                proximo_mes = f'{ano}-{numero_mes + 1:02d}-01'
            q = q.filter(Registro.horario < proximo_mes)
        except (ValueError, TypeError):
            pass
    if cidade: q=q.filter(Acao.cidade.ilike(f'%{cidade.strip()}%'))
    if data_inicio: q=q.filter(Registro.horario >= f'{data_inicio} 00:00:00')
    if data_fim: q=q.filter(Registro.horario < f'{data_fim} 23:59:59.999999')
    registros=q.order_by(Acao.data.desc(),Registro.horario.desc()).all(); prom=db.query(Promotora).order_by(Promotora.nome).all(); acoes_all=db.query(Acao).order_by(Acao.data.desc(),Acao.id.desc()).all()
    grouped={}
    for r in registros: grouped.setdefault(r.acao_id,[]).append(r)
    resumo=[{'acao':db.get(Acao,aid),'registros':rs} for aid,rs in grouped.items()]
    totals, formularios, por_promotora, por_acao = aggregate_formularios(registros)
    por_acao_data = {}
    por_acao_hora = {}
    por_hora_relatorio = {}
    for r in registros:
        if r.tipo != 'formulário':
            continue
        dia = r.horario.strftime('%d/%m/%Y')
        hora = r.horario.strftime('%H:00')
        por_hora_relatorio[hora] = por_hora_relatorio.get(hora, 0)
        try:
            d = get_json(r.dados)
            qtd = int(float(str(d.get('abordagens') or 0).replace(',', '.')))
        except Exception:
            qtd = 0
        por_hora_relatorio[hora] += qtd
        hora_bucket = por_acao_hora.setdefault((r.acao_id, dia, hora), {'acao_id':r.acao_id, 'data':dia, 'hora':hora, 'formularios':0, 'abordagens':0, 'brindes':0, 'leads':0, 'participantes':0, 'perguntas_produto':0, 'duvidas_gerais':0})
        hora_bucket['formularios'] += 1
        hora_bucket['abordagens'] += qtd
        try: hora_bucket['brindes'] += int(float(str(d.get('brindes') or 0).replace(',', '.')))
        except Exception: pass
        try: hora_bucket['leads'] += int(float(str(d.get('leads') or 0).replace(',', '.')))
        except Exception: pass
        try: hora_bucket['participantes'] += int(float(str(d.get('participantes') or 0).replace(',', '.')))
        except Exception: pass
        try: hora_bucket['perguntas_produto'] += int(float(str(d.get('perguntas_produto') or 0).replace(',', '.')))
        except Exception: pass
        try: hora_bucket['duvidas_gerais'] += int(float(str(d.get('duvidas_gerais') or 0).replace(',', '.')))
        except Exception: pass
        # Guarda o agrupamento por ação, data e hora para a tabela do relatório.
        por_acao_hora[(r.acao_id, dia, hora)] = hora_bucket
        bucket = por_acao_data.setdefault((r.acao_id, dia), {'data': dia, 'formularios': 0, 'abordagens': 0, 'leads': 0, 'brindes': 0, 'participantes': 0, 'perguntas_produto': 0, 'duvidas_gerais': 0})
        bucket['formularios'] += 1
        for key in ('abordagens','leads','brindes','participantes','perguntas_produto','duvidas_gerais'):
            try: bucket[key] += int(float(str(d.get(key) or 0).replace(',', '.')))
            except Exception: pass
    por_acao_data = sorted([{'acao_id': k[0], **v} for k,v in por_acao_data.items()], key=lambda x: (x['acao_id'], datetime.strptime(x['data'], '%d/%m/%Y')))
    por_acao_hora = sorted(por_acao_hora.values(), key=lambda x: (x['acao_id'], datetime.strptime(x['data'], '%d/%m/%Y'), x['hora']))
    db.close(); return templates.TemplateResponse(request=request,name='relatorios.html',context={'request':request,'registros':registros,'resumo':resumo,'promotoras':prom,'acoes':acoes_all,'empresa':empresa,'promotora_id':promotora_id,'acao_id':acao_id,'mes':mes,'cidade':cidade,'data_inicio':data_inicio,'data_fim':data_fim,'totals':totals,'formularios':formularios,'por_promotora':por_promotora,'por_acao':por_acao,'por_acao_data':por_acao_data,'por_acao_hora':por_acao_hora,'por_hora_relatorio':sorted(por_hora_relatorio.items())})

@app.get('/admin/acao/{acao_id}', response_class=HTMLResponse)
def detalhe_acao(request:Request,acao_id:int):
    db=SessionLocal(); acao=db.get(Acao,acao_id)
    if not acao: db.close(); return HTMLResponse('Ação não encontrada',404)
    escalas=db.query(Escala).options(joinedload(Escala.promotora)).filter_by(acao_id=acao_id).all(); registros=db.query(Registro).options(joinedload(Registro.promotora)).filter_by(acao_id=acao_id).order_by(Registro.horario.desc()).all(); selected=split_fields(acao.campos); status_rows=[]
    for e in escalas:
        s,ci,co=action_status(db,acao_id,e.promotora_id); status_rows.append({'promotora':e.promotora,'status':s,'checkin':ci,'checkout':co})
    link=str(request.base_url).rstrip('/')+f'/acao/{acao.token}'; end_time=parse_end_time(acao.horario)
    daily = {}
    hourly = {}
    for r in registros:
        if r.tipo != 'formulário': continue
        dia = r.horario.strftime('%d/%m/%Y')
        b = daily.setdefault(dia, {'formularios':0,'abordagens':0,'leads':0,'brindes':0,'participantes':0,'perguntas_produto':0,'duvidas_gerais':0})
        b['formularios'] += 1
        hora = r.horario.strftime('%H:00')
        hb = hourly.setdefault((dia, hora), {'data':dia,'hora':hora,'formularios':0,'abordagens':0,'brindes':0,'leads':0,'participantes':0,'perguntas_produto':0,'duvidas_gerais':0})
        hb['formularios'] += 1
        d = get_json(r.dados)
        for key in ('abordagens','leads','brindes','participantes','perguntas_produto','duvidas_gerais'):
            try:
                val = int(float(str(d.get(key) or 0).replace(',', '.')))
                b[key] += val
                if key in hb: hb[key] += val
            except Exception: pass
    daily = sorted(daily.items(), key=lambda item: datetime.strptime(item[0], '%d/%m/%Y'))
    hourly = sorted(hourly.values(), key=lambda item: (datetime.strptime(item['data'], '%d/%m/%Y'), item['hora']))
    db.close()
    return templates.TemplateResponse(request=request,name='acao.html',context={'request':request,'acao':acao,'escalas':escalas,'registros':registros,'selected':selected,'link':link,'status_rows':status_rows,'end_time':end_time,'daily':daily,'hourly':hourly})

@app.get('/acao/{token}', response_class=HTMLResponse)
def acessar_acao(request:Request,token:str):
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); db.close()
    if not acao: return HTMLResponse('Ação não encontrada',404)
    return templates.TemplateResponse(request=request,name='login.html',context={'request':request,'acao':acao})

@app.post('/acao/{token}/login', response_class=HTMLResponse)
def login(request:Request,token:str,codigo:str=Form(...),senha:str=Form(...)):
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); p=db.query(Promotora).filter_by(codigo=codigo.strip().upper(),ativa=1).first()
    autorizado=False
    if p and verify_password(senha, p.senha):
        autorizado=bool(acao and db.query(Escala).filter_by(acao_id=acao.id,promotora_id=p.id).first())
    if not autorizado:
        db.close(); return templates.TemplateResponse(request=request,name='login.html',context={'request':request,'acao':acao,'erro':'Código, senha ou escala inválidos.'})
    request.session['acao_token']=token; request.session['promotora_id']=p.id; db.close(); return RedirectResponse(f'/acao/{token}/checkin/{p.id}',303)

def require_promotora(request,token,promotora_id): return request.session.get('acao_token')==token and request.session.get('promotora_id')==promotora_id

@app.get('/acao/{token}/checkin/{promotora_id}',response_class=HTMLResponse)
def checkin_page(request:Request,token:str,promotora_id:int):
    if not require_promotora(request,token,promotora_id): return RedirectResponse(f'/acao/{token}',303)
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); p=db.get(Promotora,promotora_id); db.close(); return templates.TemplateResponse(request=request,name='checkin.html',context={'request':request,'acao':acao,'promotora':p})

@app.post('/acao/{token}/checkin/{promotora_id}')
def checkin(request:Request,token:str,promotora_id:int,latitude:float=Form(...),longitude:float=Form(...),precisao:str=Form('')):
    if not require_promotora(request,token,promotora_id): return RedirectResponse(f'/acao/{token}',303)
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); db.add(Registro(acao_id=acao.id,promotora_id=promotora_id,tipo='check-in',latitude=latitude,longitude=longitude,dados=json.dumps({'precisao_m':precisao}))); db.commit(); db.close(); return RedirectResponse(f'/acao/{token}/form/{promotora_id}',303)

@app.get('/acao/{token}/form/{promotora_id}',response_class=HTMLResponse)
def form_page(request:Request,token:str,promotora_id:int):
    if not require_promotora(request,token,promotora_id): return RedirectResponse(f'/acao/{token}',303)
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); p=db.get(Promotora,promotora_id); status,_,_=action_status(db,acao.id,promotora_id); db.close()
    if status=='Finalizada': return RedirectResponse(f'/acao/{token}/sucesso',303)
    return templates.TemplateResponse(request=request,name='form.html',context={'request':request,'acao':acao,'promotora':p,'selected':split_fields(acao.campos),'end_time':parse_end_time(acao.horario),'saved':request.query_params.get('saved') == '1'})

@app.post('/acao/{token}/form/{promotora_id}')
def submit_form(request:Request,token:str,promotora_id:int,abordagens:str=Form(''),leads:str=Form(''),brindes:str=Form(''),participantes:str=Form(''),perguntas_produto:str=Form(''),duvidas_gerais:str=Form(''),observacoes:str=Form(''),foto:UploadFile|None=File(None)):
    if not require_promotora(request,token,promotora_id): return RedirectResponse(f'/acao/{token}',303)
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); foto_url=save_photo(foto); dados=json.dumps({'abordagens':abordagens,'leads':leads,'brindes':brindes,'participantes':participantes,'perguntas_produto':perguntas_produto,'duvidas_gerais':duvidas_gerais,'observacoes':observacoes},ensure_ascii=False); db.add(Registro(acao_id=acao.id,promotora_id=promotora_id,tipo='formulário',dados=dados,foto=foto_url)); db.commit(); db.close(); return RedirectResponse(f'/acao/{token}/form/{promotora_id}?saved=1',303)

@app.get('/acao/{token}/checkout/{promotora_id}',response_class=HTMLResponse)
def checkout_page(request:Request,token:str,promotora_id:int):
    if not require_promotora(request,token,promotora_id): return RedirectResponse(f'/acao/{token}',303)
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); p=db.get(Promotora,promotora_id); status,_,_=action_status(db,acao.id,promotora_id); db.close()
    if status=='Finalizada': return RedirectResponse(f'/acao/{token}/sucesso',303)
    return templates.TemplateResponse(request=request,name='checkout.html',context={'request':request,'acao':acao,'promotora':p,'end_time':parse_end_time(acao.horario)})

@app.post('/acao/{token}/checkout/{promotora_id}')
def checkout(request:Request,token:str,promotora_id:int,latitude:float=Form(...),longitude:float=Form(...),precisao:str=Form('')):
    if not require_promotora(request,token,promotora_id): return RedirectResponse(f'/acao/{token}',303)
    db=SessionLocal(); acao=db.query(Acao).filter_by(token=token).first(); db.add(Registro(acao_id=acao.id,promotora_id=promotora_id,tipo='check-out',latitude=latitude,longitude=longitude,dados=json.dumps({'precisao_m':precisao}))); db.commit(); db.close(); request.session.clear(); return RedirectResponse(f'/acao/{token}/sucesso',303)



def cliente_autenticado(request: Request):
    return bool(request.session.get('client_user_id'))

@app.get('/cliente/login', response_class=HTMLResponse)
def cliente_login_page(request: Request):
    if cliente_autenticado(request): return RedirectResponse('/cliente', status_code=303)
    return templates.TemplateResponse(request=request, name='cliente_login.html', context={'request':request})

@app.post('/cliente/login', response_class=HTMLResponse)
def cliente_login(request: Request, usuario: str=Form(...), senha: str=Form(...)):
    db=SessionLocal(); u=db.query(Usuario).filter_by(usuario=usuario.strip(), ativo=1, perfil='Cliente').first()
    if not u or not verify_password(senha,u.senha):
        db.close(); return templates.TemplateResponse(request=request,name='cliente_login.html',context={'request':request,'erro':'Usuário ou senha inválidos.'})
    request.session['client_user_id']=u.id; db.close(); return RedirectResponse('/cliente',303)

@app.get('/cliente/logout')
def cliente_logout(request:Request):
    request.session.pop('client_user_id',None); return RedirectResponse('/cliente/login',303)

@app.get('/cliente', response_class=HTMLResponse)
def cliente_dashboard(request:Request):
    if not cliente_autenticado(request): return RedirectResponse('/cliente/login',303)
    db=SessionLocal(); u=db.get(Usuario,request.session['client_user_id']); cliente=db.get(Cliente,u.cliente_id) if u and u.cliente_id else None
    acoes=db.query(Acao).filter(Acao.cliente==cliente.nome if cliente else '').order_by(Acao.data.desc(),Acao.id.desc()).all()
    ids=[a.id for a in acoes]
    registros=db.query(Registro).filter(Registro.acao_id.in_(ids)).order_by(Registro.horario).all() if ids else []
    totals, formularios, por_promotora, por_acao=aggregate_formularios(registros)
    brindes_disp=sum(a.brindes_disponiveis or 0 for a in acoes); brindes_ent=totals['brindes']; atend=totals['abordagens']
    por_hora={}; por_dia={}
    for r in registros:
        if r.tipo!='formulário': continue
        d=get_json(r.dados); hora=r.horario.strftime('%H:00'); dia=r.horario.strftime('%d/%m/%Y')
        por_hora[hora]=por_hora.get(hora,0)+int(float(d.get('abordagens') or 0))
        por_dia.setdefault(dia,{'atendidos':0,'brindes':0,'perguntas':0,'duvidas':0})
        por_dia[dia]['atendidos']+=int(float(d.get('abordagens') or 0)); por_dia[dia]['brindes']+=int(float(d.get('brindes') or 0)); por_dia[dia]['perguntas']+=int(float(d.get('perguntas_produto') or 0)); por_dia[dia]['duvidas']+=int(float(d.get('duvidas_gerais') or 0))
    db.close()
    por_hora = sorted(por_hora.items())
    max_hora = max([v for _,v in por_hora], default=1) or 1
    max_dia = max([v['atendidos'] for v in por_dia.values()], default=1) or 1
    return templates.TemplateResponse(request=request,name='cliente_dashboard.html',context={'request':request,'cliente':cliente,'acoes':acoes,'totals':totals,'brindes_disp':brindes_disp,'brindes_ent':brindes_ent,'saldo_brindes':max(0,brindes_disp-brindes_ent),'por_hora':por_hora,'por_dia':por_dia,'max_hora':max_hora,'max_dia':max_dia})

@app.get('/acao/{token}/sucesso',response_class=HTMLResponse)
def sucesso(request:Request,token:str): return templates.TemplateResponse(request=request,name='sucesso.html',context={'request':request})
