# Painel de Indicadores de Rio Preto

Módulo Django público e isolado para acompanhar as seis dimensões e os 22
eixos estratégicos da cidade. A hierarquia é sempre:

`dimensão → eixo → indicador → medição → fonte`

O painel público fica em `/indicadores/`. A administração dos cadastros também
está disponível no Django Admin, e usuários `is_staff` podem inserir ou revisar
medições diretamente pelo painel.

## Princípios de dados

- O catálogo define nomes, fórmulas, unidades, polaridade e frequência sem
  obrigar a existência de uma medição.
- Ausência de dado é exibida como ausência, nunca como zero.
- Metas são opcionais e não são inferidas pelo sistema.
- Cada medição preserva período, qualidade, fonte, observação e detalhamentos
  em JSON.
- A chave natural `indicador + início + fim do período` torna cargas repetidas
  idempotentes.
- Valores históricos extraídos da *Conjuntura Econômica 2025* registram a
  página de origem na observação da medição.

## Primeira carga

Sincronize o catálogo e os dados-base:

```powershell
python manage.py sync_municipal_catalog
```

O comando pode ser executado novamente com segurança. Ele atualiza a estrutura
do catálogo e preserva medições que já existam para o mesmo indicador e
período.

## Importação por CSV

Use `municipal_dashboard/data/modelo_importacao.csv` como modelo:

```powershell
python manage.py import_municipal_data caminho\medicoes.csv --dry-run
python manage.py import_municipal_data caminho\medicoes.csv
```

O modo `--dry-run` valida a carga inteira e desfaz a transação. O importador
aceita o identificador estável do indicador e faz *upsert* pelo período.

## API

- `GET /indicadores/api/overview/`
- `GET /indicadores/api/indicators/<slug>/`
- `GET /indicadores/api/freshness/`
- `POST /indicadores/api/measurements/` — somente equipe autenticada, com CSRF

Filtros do resumo:

- `year=2024` ou `year=all`
- `dimension=<slug-ou-id>`
- `axis=<slug-ou-id>`
- `q=<busca>`

O endpoint de escrita aceita uma medição, uma lista ou um envelope com
`measurements`. Exemplo:

```json
{
  "indicator_slug": "saldo-empregos-formais",
  "period_start": "2025-01-01",
  "period_end": "2025-01-31",
  "value": 640,
  "quality": "official",
  "source_name": "Novo Caged",
  "breakdown": {
    "servicos": 320,
    "comercio": 180
  }
}
```

## Atualização quase em tempo real

O navegador consulta a rota de frescor periodicamente. Quando detecta uma nova
gravação, atualiza o conjunto filtrado sem recarregar a página. Isso funciona
no stack atual de Django/Gunicorn/Render sem exigir WebSockets.

Para integrações automáticas, um processo do Django Q pode consultar a fonte,
normalizar o resultado no mesmo contrato da API e gravar em lote. Fontes
mensais ou anuais continuam usando a mesma estrutura; apenas a frequência e o
período mudam.

## Decisões que ainda exigem validação institucional

- O encaixe dos seis eixos que chegaram sem dimensão e sem indicadores.
- Metas oficiais e regra de semáforo para cada indicador.
- Secretaria responsável, periodicidade e data de fechamento de cada fonte.
- Granularidade territorial oficial (região administrativa, unidade, bairro
  ou outra).
- Política de revisão e publicação de dados provisórios.
