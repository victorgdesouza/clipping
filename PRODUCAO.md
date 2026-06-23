# Guia rapido de producao

Este projeto esta preparado para o servico web existente `clipping` no Render.
O Gunicorn e um worker Django Q rodam juntos por meio de `start_render.sh`.

## Topologia atual

- Um unico servico web Django: `clipping`
- Gunicorn para requisicoes HTTP
- Um worker Django Q no mesmo servico
- PostgreSQL configurado pela variavel `DATABASE_URL`

Nao existem, na topologia atual, servicos separados chamados
`clipping-app-worker` ou `clipping-app-fetch-news`.

## Antes de publicar

1. Garanta que `.env`, `db.sqlite3`, `staticfiles/` e `__pycache__/` nao sejam enviados ao Git.
2. Suba o repositorio para GitHub ou GitLab.
3. No servico `clipping`, configure as variaveis secretas em **Environment**.
4. Nunca copie valores reais para `render.yaml` ou `.env.example`.

## Variaveis no Render

Credenciais administrativas obrigatorias:

- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_EMAIL`
- `DJANGO_SUPERUSER_PASSWORD`

Provedores opcionais de noticias e descoberta:

- `NEWSAPI_API_KEY`
- `NEWSDATA_API_KEY`
- `GOOGLE_API_KEY`
- `GOOGLE_CSE_ID`
- `YOUTUBE_API_KEY`
- `BRAVE_SEARCH_API_KEY`

As chaves de APIs de noticias podem ficar vazias. Sem `BRAVE_SEARCH_API_KEY`,
o motor continua usando Google News RSS e as fontes cadastradas, mas nao executa
a descoberta ampla de novos dominios.

## Depois do primeiro deploy

1. Acesse a URL `.onrender.com` criada pelo Render.
2. Entre em `/admin/` com o superusuario configurado.
3. Cadastre fontes em `Sources`.
4. Cadastre clientes no dashboard.
5. Teste `Buscar noticias` em um cliente.
6. Gere e valide os relatorios. O PDF usa ReportLab e nao depende de
   `wkhtmltopdf`.

## Coleta

A coleta iniciada no painel e enviada ao worker Django Q que roda no proprio
servico `clipping`. Um agendamento automatico separado ainda nao esta ativo no
Render atual.

A descoberta ampla do Brave roda no maximo uma vez a cada 24 horas por cliente.
As demais rodadas continuam consultando RSS, sitemaps e fontes ja conhecidas.
Use `--force-run` apenas para testes controlados que precisem ignorar esse
intervalo.

Quando o Brave encontra uma materia relevante, o sistema:

1. salva a evidencia em `Discovery results`;
2. registra o dominio como fonte candidata;
3. procura RSS e sitemaps na pagina e no `robots.txt`;
4. passa a consultar os endpoints encontrados nas coletas seguintes.

O historico e o consumo logico de cada campanha ficam em `Discovery runs` no admin.

Para automatizar a coleta no futuro, crie um Cron Job separado ou um agendador
equivalente depois de avaliar custo e volume.

## Comandos uteis

Rodar localmente:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Checar configuracao:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

Rodar testes:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

Coletar noticias manualmente:

```powershell
.\.venv\Scripts\python.exe manage.py fetch_news
```

Coletar noticias de um cliente especifico:

```powershell
.\.venv\Scripts\python.exe manage.py fetch_news --client-id 12
```

## Observacoes importantes

- Em producao, use PostgreSQL. SQLite deve ficar apenas para desenvolvimento local.
- Nao publique o arquivo `.env`.
- Troque qualquer senha temporaria antes de usar com clientes reais.
- Se configurar um dominio proprio, adicione o dominio em `ALLOWED_HOSTS` e em `CSRF_TRUSTED_ORIGINS`.
