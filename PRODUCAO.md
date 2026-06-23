# Guia rapido de producao

Este projeto esta preparado para deploy no Render usando `render.yaml`.

## O que o Render vai criar

- Um servico web Django: `clipping-app-web`
- Um banco PostgreSQL: `clipping-app-db`
- Um worker Django Q: `clipping-app-worker`
- Um cron de coleta de noticias a cada 6 horas: `clipping-app-fetch-news`

## Antes de publicar

1. Garanta que `.env`, `db.sqlite3`, `staticfiles/` e `__pycache__/` nao sejam enviados ao Git.
2. Suba o repositorio para GitHub ou GitLab.
3. No Render, crie um Blueprint apontando para este repositorio.
4. Durante a criacao, preencha as variaveis marcadas como `sync: false`.

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
6. Gere relatorios em CSV/XLSX primeiro; PDF depende de `wkhtmltopdf`.

## Coleta automatica

O cron `clipping-app-fetch-news` roda:

```text
0 */6 * * *
```

Isso significa: a cada 6 horas.

A descoberta ampla do Brave roda no maximo uma vez a cada 24 horas por cliente,
mesmo com o cron de seis horas. As demais rodadas continuam consultando RSS,
sitemaps e fontes ja conhecidas. Use `--force-run` apenas para testes controlados
que precisem ignorar esse intervalo.

Quando o Brave encontra uma materia relevante, o sistema:

1. salva a evidencia em `Discovery results`;
2. registra o dominio como fonte candidata;
3. procura RSS e sitemaps na pagina e no `robots.txt`;
4. passa a consultar os endpoints encontrados nas coletas seguintes.

O historico e o consumo logico de cada campanha ficam em `Discovery runs` no admin.

Para mudar a frequencia, edite o campo `schedule` em `render.yaml`.

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
