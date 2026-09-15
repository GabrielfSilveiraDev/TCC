# TCC — Remunerações dos Tribunais de Contas Estaduais (backend)

Pipeline de coleta automatizada, normalização, carga em banco analítico e API de leitura dos dados de remuneração
dos servidores dos Tribunais de Contas Estaduais (ES, MG, PR, RJ, RS, SC e SP). O painel em React fica em um
repositório separado.

## Estrutura

| Caminho | Papel |
|---|---|
| `Scrapers/` | Coletores por tribunal (`webscraper_<uf>.py`) e dados brutos em `Dados_<UF>/` |
| `normalize_data.py` | Converte os JSONs brutos para o esquema canônico em `Dados_Normalizados/` |
| `schema.sql` | Esquema estrela no SQL Server (`dim_estado`, `dim_cargo`, `fato_remuneracao`, `vw_remuneracao_completa`) |
| `load_data.py` | Carrega os dados normalizados (e o CSV de MG) no banco |
| `api/` | API FastAPI somente leitura consumida pelo painel |
| `settings.py` | Configuração de conexão lida do `.env` |
| `docker-compose.yml` | SQL Server 2025 com volume persistente e criação automática do schema |

## Pré-requisitos

- Python 3.12
- Docker Desktop
- Driver ODBC 17 for SQL Server (para `pyodbc`)
- Google Chrome (coletores com Selenium)

## Como executar

```bash
# 1. Ambiente Python
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Configuração: copie o modelo e preencha DB_PASSWORD
copy .env.example .env

# 3. Banco de dados (na primeira vez também aplica schema.sql)
docker compose up -d

# 4. Coleta (exemplo: TCE-SC), normalização e carga
cd Scrapers && python webscraper_sc.py && cd ..
python normalize_data.py
python load_data.py            # ou: python load_data.py --estado SC

# 5. API (documentação interativa em http://localhost:8000/docs)
uvicorn api.main:app --reload --port 8000
```

`schema.sql` executado manualmente faz `DROP DATABASE` e apaga a carga existente; o `docker compose` só o aplica
quando o banco ainda não existe.
