# PromoGo — Versão Cloud para Apresentação

Versão web do painel administrativo PromoGo, preparada para publicação no Render com PostgreSQL e dados fictícios.

## Acesso de demonstração
- Usuário ADM: `admin`
- Senha ADM: `123456`
- Promotora: `PRO001`
- Senha: `123456`
- Ação de teste: `/acao/TESTE001`

## Publicação no Render
O `render.yaml` cria automaticamente:
1. o Web Service `promogo-admin`;
2. um PostgreSQL `promogo-db`;
3. `DATABASE_URL` ligado ao banco;
4. uma chave de sessão aleatória;
5. HTTPS obrigatório;
6. carga automática dos dados fictícios na primeira inicialização.

### Passos
1. Suba esta pasta para um repositório GitHub.
2. No Render, escolha **New → Blueprint** e conecte o repositório.
3. O Render lerá o `render.yaml`.
4. Confirme a criação do Web Service e do Postgres.
5. Aguarde o deploy e abra a URL `.onrender.com`.

O Blueprint usa Postgres porque o SQLite/local filesystem não é adequado para uma aplicação web publicada. O Render informa que o Postgres gratuito existe para testes, mas expira após 30 dias; para uso real, troque o banco para um plano pago antes de colocar dados verdadeiros.

## Dados fictícios
Se `PROMOGO_SEED_DEMO=true`, o sistema cria automaticamente dados de demonstração apenas quando o banco ainda não possui ações. Reinícios não duplicam os dados.

## Segurança
- Senhas novas são armazenadas com PBKDF2-SHA256.
- A sessão usa `PROMOGO_SECRET_KEY` gerada pelo Render.
- Cookies seguros podem ser ativados com `PROMOGO_HTTPS_ONLY=true`.

## Observação de produção real
Esta versão é **cloud e apresentável**, mas ainda usa armazenamento local para fotos enviadas pelas ações. Para operação real com fotos, recomenda-se adicionar armazenamento de objetos (S3/Cloudinary/R2) e backups/monitoramento antes de começar a registrar dados reais.


## Atualizações da V7.3

- Relatório da ação com consolidação dos resultados por data.
- Relatório da ação e relatório geral com consolidação por faixa horária, usando o horário de envio de cada formulário.
- A promotora pode salvar vários formulários durante a mesma ação; cada envio fica como registro separado, com seu próprio timestamp.
- Após salvar, a tela oferece a opção de preencher outro registro ou fazer check-out.
- Portal do cliente inclui gráficos de barras por dia e por hora, sem depender de biblioteca externa de gráficos.

Para iniciar localmente, dentro da pasta que contém `app` e `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
