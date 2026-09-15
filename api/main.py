"""
main.py â€” API FastAPI para o dashboard de remuneraÃ§Ãµes TCE.

Iniciar:
    uvicorn api.main:app --reload --port 8000

Docs interativas:
    http://localhost:8000/docs
"""

import math
from typing import Annotated, Optional
from fastapi import FastAPI, Query, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import unquote
import pyodbc

from api.database import get_conn

app = FastAPI(
    title="TCE RemuneraÃ§Ãµes API",
    version="1.0.0",
    description="Dados de remuneraÃ§Ã£o de servidores pÃºblicos â€” ES, SP, MG, RS, PR, SC",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://localhost:8080",
    ],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

ESTADOS_VALIDOS = {"ES", "SP", "MG", "RS", "PR", "SC", "RJ"}

CPF_MASCARA = "***.***.***-**"


def _rows_to_list(cursor: pyodbc.Cursor) -> list[dict]:
    cols = [col[0] for col in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _parse_competencia(competencia: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """'2025-01' â†’ (2025, 1). Retorna (None, None) se invÃ¡lido."""
    if not competencia:
        return None, None
    try:
        parts = competencia.strip().split("-")
        return int(parts[0]), int(parts[1])
    except Exception:
        raise HTTPException(status_code=400, detail="Formato de competencia invÃ¡lido. Use YYYY-MM.")


def _to_servidor_out(row: dict) -> dict:
    """Mapeia campos internos para o formato esperado pelo frontend."""
    competencia = None
    mes = row.get("mes")
    ano = row.get("ano")
    if mes and ano:
        competencia = f"{ano}-{str(mes).zfill(2)}"

    return {
        "id":                 str(row.get("id")),
        "matricula":          row.get("matricula"),
        "nome":               row.get("nome"),
        "cpf":                CPF_MASCARA,
        "cargo":              row.get("cargo"),
        "orgao":              row.get("lotacao"),
        "estado":             row.get("estado"),
        "salario_base":       row.get("salario_base"),
        "remuneracao_bruta":  row.get("rendimento_bruto"),
        "descontos":          row.get("descontos"),
        "beneficios":         row.get("beneficios"),
        "remuneracao_liquida": row.get("salario_liquido"),
        "competencia":        competencia,
        "tem_historico":      row.get("matricula") not in (None, ""),
    }


# --- Novos endpoints (contrato com o frontend) ----------------------------

SORT_COLUMN_MAP = {
    "remuneracao_bruta":   "rendimento_bruto",
    "rendimento_bruto":    "rendimento_bruto",
    "remuneracao_liquida": "salario_liquido",
    "salario_liquido":     "salario_liquido",
    "renda_total":         "rendimento_bruto",
    "nome":                "nome",
    "cargo":               "cargo",
    "estado":              "estado",
    "descontos":           "descontos",
    "beneficios":          "beneficios",
    "competencia":         "ano, mes",
}


@app.get("/servidores", summary="Lista servidores com paginaÃ§Ã£o e filtros")
def listar_servidores(
    page:        Annotated[int, Query(ge=1)]                                                          = 1,
    page_size:   Annotated[int, Query(ge=1, le=200)]                                                  = 25,
    nome:        Annotated[Optional[str], Query(description="Busca parcial no nome")]                 = None,
    cargo:       Annotated[Optional[str], Query(description="Busca parcial no cargo")]                = None,
    estado:      Annotated[Optional[str], Query(description="Sigla UF")]                              = None,
    competencia: Annotated[Optional[str], Query(description="Formato YYYY-MM")]                       = None,
    sort_by:     Annotated[Optional[str], Query(description="Campo de ordenaÃ§Ã£o")]                    = None,
    sort_order:  Annotated[Optional[str], Query(description="'asc' ou 'desc'", pattern="^(asc|desc)$")] = "desc",
):
    filters: list[str] = []
    params:  list      = []

    if estado:
        filters.append("estado = ?")
        params.append(estado.upper())
    if nome:
        filters.append("nome LIKE ?")
        params.append(f"%{nome}%")
    if cargo:
        filters.append("cargo LIKE ?")
        params.append(f"%{cargo}%")
    if competencia:
        ano, mes = _parse_competencia(competencia)
        filters.append("ano = ? AND mes = ?")
        params.append(ano)
        params.append(mes)

    where  = ("WHERE " + " AND ".join(filters)) if filters else ""
    offset = (page - 1) * page_size

    sql_col = SORT_COLUMN_MAP.get(sort_by) if sort_by else None
    order_dir = "DESC" if (sort_order or "desc").lower() == "desc" else "ASC"
    order_clause = f"ORDER BY {sql_col} {order_dir}" if sql_col else "ORDER BY rendimento_bruto DESC"

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute(
        f"""
        SELECT id, estado, matricula, nome, cargo, lotacao, situacao,
               mes, ano, mes_ano,
               salario_base, beneficios, descontos,
               rendimento_bruto, salario_liquido
        FROM dbo.vw_remuneracao_mensal
        {where}
        {order_clause}
        OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
        """,
        *params, offset, page_size,
    )
    rows = _rows_to_list(cur)

    cur.execute(f"SELECT COUNT(*) FROM dbo.vw_remuneracao_mensal {where}", *params)
    total = cur.fetchone()[0]

    return {
        "items":       [_to_servidor_out(r) for r in rows],
        "total":       total,
        "page":        page,
        "page_size":   page_size,
        "total_pages": math.ceil(total / page_size) if total else 1,
    }


@app.get("/servidores/{servidor_id}", summary="Detalhe de um servidor")
def detalhe_servidor(servidor_id: str):
    conn = get_conn()
    cur  = conn.cursor()
    # Localiza a competência pela folha (id) e só então consulta a visão mensal pela chave,
    # evitando agregar toda a base para filtrar um único id.
    cur.execute(
        """
        SELECT f.estado_id, f.matricula, f.ano, f.mes
        FROM dbo.fato_remuneracao f
        WHERE f.id = ?
        """,
        int(servidor_id),
    )
    chave = cur.fetchone()
    if not chave:
        raise HTTPException(status_code=404, detail="Servidor não encontrado")
    cur.execute(
        """
        SELECT m.id, m.estado, m.matricula, m.nome, m.cargo, m.lotacao, m.situacao,
               m.mes, m.ano, m.mes_ano,
               m.salario_base, m.beneficios, m.descontos,
               m.rendimento_bruto, m.salario_liquido
        FROM dbo.vw_remuneracao_mensal m
        JOIN dbo.dim_estado e ON e.sigla = m.estado
        WHERE e.estado_id = ? AND m.matricula = ? AND m.ano = ? AND m.mes = ?
        """,
        chave[0], chave[1], chave[2], chave[3],
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Servidor nÃ£o encontrado")
    cols = [c[0] for c in cur.description]
    return _to_servidor_out(dict(zip(cols, row)))


@app.get("/estados/resumo", summary="Resumo salarial de todos os estados")
def resumo_todos_estados():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            estado,
            COUNT(*)                 AS total_servidores,
            AVG(rendimento_bruto)    AS media_bruta,
            AVG(salario_liquido)     AS media_liquida,
            AVG(descontos)           AS media_descontos,
            AVG(beneficios)          AS media_beneficios
        FROM dbo.vw_remuneracao_mensal
        GROUP BY estado
        ORDER BY estado ASC
        """
    )
    return _rows_to_list(cur)


@app.get("/estados/{sigla}/resumo", summary="Resumo salarial de um estado")
def resumo_estado(sigla: str):
    sigla = sigla.upper()
    if sigla not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=404, detail=f"Estado '{sigla}' nÃ£o encontrado.")

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            estado,
            COUNT(*)                 AS total_servidores,
            AVG(rendimento_bruto)    AS media_bruta,
            AVG(salario_liquido)     AS media_liquida,
            AVG(descontos)           AS media_descontos,
            AVG(beneficios)          AS media_beneficios
        FROM dbo.vw_remuneracao_mensal
        WHERE estado = ?
        GROUP BY estado
        """,
        sigla,
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Sem dados para o estado '{sigla}'.")
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


@app.get("/overview/kpis", summary="KPIs nacionais (opcionalmente filtrado por competencia)")
def overview_kpis(
    competencia: Annotated[Optional[str], Query(description="Formato YYYY-MM")] = None,
):
    periodo_filter = ""
    params_kpi: list = []
    params_anterior: list = []

    if competencia:
        ano, mes = _parse_competencia(competencia)
        periodo_filter = "WHERE ano = ? AND mes = ?"
        params_kpi = [ano, mes]

        mes_ant = mes - 1 if mes > 1 else 12
        ano_ant = ano if mes > 1 else ano - 1
        params_anterior = [ano_ant, mes_ant]

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute(
        f"""
        SELECT
            COUNT(*)                     AS total_servidores,
            AVG(rendimento_bruto)        AS media_nacional_bruta,
            AVG(salario_liquido)         AS media_nacional_liquida,
            SUM(rendimento_bruto)        AS total_folha
        FROM dbo.vw_remuneracao_mensal
        {periodo_filter}
        """,
        *params_kpi,
    )
    row  = cur.fetchone()
    cols = [c[0] for c in cur.description]
    data = dict(zip(cols, row))

    variacao_mes = None
    if params_anterior:
        cur.execute(
            """
            SELECT AVG(rendimento_bruto) AS media_anterior
            FROM dbo.vw_remuneracao_mensal
            WHERE ano = ? AND mes = ?
            """,
            *params_anterior,
        )
        row_ant = cur.fetchone()
        media_ant = row_ant[0] if row_ant else None
        media_atual = data.get("media_nacional_bruta")
        if media_ant and media_ant != 0 and media_atual:
            variacao_mes = round(((float(media_atual) - float(media_ant)) / float(media_ant)) * 100, 2)

    data["variacao_mes"] = variacao_mes
    return data


@app.get("/overview/historico", summary="EvoluÃ§Ã£o mensal das mÃ©dias nacionais")
def overview_historico(
    inicio: Annotated[str, Query(description="Competencia inicial, ex: 2020-01")],
    fim:    Annotated[Optional[str], Query(description="Competencia final, ex: 2025-12")] = None,
):
    ano_ini, mes_ini = _parse_competencia(inicio)

    fim_filter = ""
    params: list = [ano_ini * 100 + mes_ini]

    if fim:
        ano_fim, mes_fim = _parse_competencia(fim)
        fim_filter = "AND (ano * 100 + mes) <= ?"
        params.append(ano_fim * 100 + mes_fim)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        f"""
        SELECT
            ano,
            mes,
            AVG(rendimento_bruto)  AS media_bruta,
            AVG(salario_liquido)   AS media_liquida,
            AVG(descontos)         AS media_descontos
        FROM dbo.vw_remuneracao_mensal
        WHERE (ano * 100 + mes) >= ?
        {fim_filter}
        GROUP BY ano, mes
        ORDER BY ano ASC, mes ASC
        """,
        *params,
    )
    rows = _rows_to_list(cur)
    return [
        {
            "competencia":    f"{r['ano']}-{str(r['mes']).zfill(2)}",
            "media_bruta":    r["media_bruta"],
            "media_liquida":  r["media_liquida"],
            "media_descontos": r["media_descontos"],
        }
        for r in rows
    ]


@app.get("/servidores/{estado}/{matricula}/historico", summary="HistÃ³rico mensal de um servidor por estado+matrÃ­cula")
def historico_servidor(estado: str, matricula: str):
    sigla = estado.upper()
    if sigla not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado '{sigla}' invÃ¡lido.")

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT mes, ano, salario_base, rendimento_bruto, descontos, beneficios, salario_liquido
        FROM dbo.vw_remuneracao_mensal
        WHERE estado = ? AND matricula = ?
        ORDER BY ano ASC, mes ASC
        """,
        sigla, matricula,
    )
    rows = _rows_to_list(cur)
    if not rows:
        raise HTTPException(status_code=404, detail="Servidor nÃ£o encontrado.")
    return [
        {
            "competencia":         f"{r['ano']}-{str(r['mes']).zfill(2)}",
            "salario_base":        r["salario_base"],
            "remuneracao_bruta":   r["rendimento_bruto"],
            "descontos":           r["descontos"],
            "beneficios":          r["beneficios"],
            "remuneracao_liquida": r["salario_liquido"],
        }
        for r in rows
    ]


@app.get("/cargos", summary="Lista todos os cargos distintos")
def listar_cargos():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "SELECT cargo_id AS id, descricao FROM dbo.dim_cargo ORDER BY descricao ASC"
    )
    return _rows_to_list(cur)


@app.get("/cargos/resumo", summary="Resumo salarial por cargo")
def resumo_cargos():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            cargo                   AS cargo,
            COUNT(*)                AS total_servidores,
            AVG(rendimento_bruto)   AS media_bruta,
            AVG(salario_liquido)    AS media_liquida,
            AVG(descontos)          AS media_descontos,
            AVG(beneficios)         AS media_beneficios
        FROM dbo.vw_remuneracao_mensal
        WHERE cargo IS NOT NULL
        GROUP BY cargo
        ORDER BY AVG(rendimento_bruto) DESC
        """
    )
    return _rows_to_list(cur)


@app.get("/cargos/{cargo}/resumo", summary="Resumo de um cargo especÃ­fico")
def resumo_cargo_especifico(cargo: str = Path(...)):
    cargo_decoded = unquote(cargo).upper()
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            cargo                   AS cargo,
            COUNT(*)                AS total_servidores,
            AVG(rendimento_bruto)      AS media_bruta,
            AVG(salario_liquido)    AS media_liquida,
            AVG(descontos)          AS media_descontos,
            AVG(beneficios)         AS media_beneficios
        FROM dbo.vw_remuneracao_mensal
        WHERE cargo = ?
        GROUP BY cargo
        """,
        cargo_decoded,
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Cargo '{cargo_decoded}' nÃ£o encontrado.")
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


@app.get("/cargos/{cargo}/estados/resumo", summary="DistribuiÃ§Ã£o de um cargo pelos estados")
def resumo_cargo_por_estados(cargo: str = Path(...)):
    cargo_decoded = unquote(cargo).upper()
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            estado,
            COUNT(*)                AS total_servidores,
            AVG(rendimento_bruto)      AS media_bruta,
            AVG(salario_liquido)    AS media_liquida,
            AVG(descontos)          AS media_descontos,
            AVG(beneficios)         AS media_beneficios
        FROM dbo.vw_remuneracao_mensal
        WHERE cargo = ?
        GROUP BY estado
        ORDER BY AVG(rendimento_bruto) DESC
        """,
        cargo_decoded,
    )
    rows = _rows_to_list(cur)
    if not rows:
        raise HTTPException(status_code=404, detail=f"Cargo '{cargo_decoded}' nÃ£o encontrado.")
    return rows


@app.get("/estados/{sigla}/cargos/resumo", summary="Top cargos de um estado")
def resumo_cargos_estado(sigla: str):
    sigla = sigla.upper()
    if sigla not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=404, detail=f"Estado '{sigla}' nÃ£o encontrado.")

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            cargo,
            COUNT(*)                AS total_servidores,
            AVG(rendimento_bruto)      AS media_bruta,
            AVG(salario_liquido)    AS media_liquida,
            AVG(descontos)          AS media_descontos,
            AVG(beneficios)         AS media_beneficios
        FROM dbo.vw_remuneracao_mensal
        WHERE estado = ? AND cargo IS NOT NULL
        GROUP BY cargo
        ORDER BY AVG(rendimento_bruto) DESC
        """,
        sigla,
    )
    return _rows_to_list(cur)


# --- Endpoints legados (usados pelo Streamlit) ----------------------------

@app.get("/estados", summary="Lista os estados disponÃ­veis")
def listar_estados():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT sigla, nome FROM dbo.dim_estado ORDER BY sigla")
    return _rows_to_list(cur)


@app.get("/periodos", summary="Lista os anos/meses com dados")
def listar_periodos(
    estado: Annotated[Optional[str], Query(description="Sigla UF")] = None
):
    conn = get_conn()
    cur  = conn.cursor()
    if estado:
        cur.execute(
            """
            SELECT DISTINCT f.ano, f.mes
            FROM dbo.fato_remuneracao f
            JOIN dbo.dim_estado e ON e.estado_id = f.estado_id
            WHERE e.sigla = ?
            ORDER BY f.ano, f.mes
            """,
            estado.upper(),
        )
    else:
        cur.execute("SELECT DISTINCT ano, mes FROM dbo.fato_remuneracao ORDER BY ano, mes")
    return _rows_to_list(cur)


@app.get("/ranking", summary="Top N salÃ¡rios por perÃ­odo e estado")
def ranking(
    ano:    Annotated[int,           Query(ge=2000, le=2100)] = 2024,
    mes:    Annotated[int,           Query(ge=1, le=12)]      = 1,
    estado: Annotated[Optional[str], Query()]                 = None,
    top:    Annotated[int,           Query(ge=1, le=200)]     = 20,
):
    filters = ["ano = ?", "mes = ?"]
    params: list = [ano, mes]
    if estado:
        filters.append("estado = ?")
        params.append(estado.upper())

    where = "WHERE " + " AND ".join(filters)
    conn  = get_conn()
    cur   = conn.cursor()
    cur.execute(
        f"""
        SELECT TOP (?) nome, cargo, estado, mes_ano,
               salario_base, beneficios, descontos,
               rendimento_bruto, salario_liquido
        FROM dbo.vw_remuneracao_mensal
        {where}
        ORDER BY rendimento_bruto DESC
        """,
        top, *params,
    )
    return _rows_to_list(cur)


@app.get("/evolucao", summary="EvoluÃ§Ã£o mensal mÃ©dia por estado")
def evolucao(
    estado:  Annotated[str,           Query(description="Sigla UF")]      = "SC",
    cargo:   Annotated[Optional[str], Query(description="Busca parcial")] = None,
    ano_ini: Annotated[int,           Query(ge=2000)]                     = 2020,
    ano_fim: Annotated[int,           Query(le=2100)]                     = 2025,
):
    if estado.upper() not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado invÃ¡lido. Use: {ESTADOS_VALIDOS}")

    params: list = [estado.upper(), ano_ini, ano_fim]
    cargo_filter = ""
    if cargo:
        cargo_filter = "AND cargo LIKE ?"
        params.append(f"%{cargo}%")

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        f"""
        SELECT
            ano, mes, mes_ano,
            COUNT(*)             AS total_servidores,
            AVG(salario_base)    AS media_base,
            AVG(beneficios)      AS media_beneficios,
            AVG(descontos)       AS media_descontos,
            AVG(rendimento_bruto)   AS media_bruto,
            AVG(salario_liquido) AS media_liquido
        FROM dbo.vw_remuneracao_mensal
        WHERE estado = ? AND ano BETWEEN ? AND ?
        {cargo_filter}
        GROUP BY ano, mes, mes_ano
        ORDER BY ano, mes
        """,
        *params,
    )
    return _rows_to_list(cur)


@app.get("/comparacao/cargos", summary="ComparaÃ§Ã£o salarial entre cargos num perÃ­odo")
def comparacao_cargos(
    ano:    Annotated[int,           Query(ge=2000, le=2100)] = 2024,
    mes:    Annotated[int,           Query(ge=1, le=12)]      = 1,
    estado: Annotated[Optional[str], Query()]                 = None,
    top:    Annotated[int,           Query(ge=1, le=50)]      = 10,
):
    params: list = [ano, mes]
    estado_filter = ""
    if estado:
        estado_filter = "AND estado = ?"
        params.append(estado.upper())

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        f"""
        SELECT TOP (?)
            cargo,
            COUNT(*)             AS total_servidores,
            AVG(rendimento_bruto)   AS media_bruto,
            AVG(salario_liquido) AS media_liquido,
            MAX(rendimento_bruto)   AS max_bruto
        FROM dbo.vw_remuneracao_mensal
        WHERE ano = ? AND mes = ? AND cargo IS NOT NULL
        {estado_filter}
        GROUP BY cargo
        ORDER BY media_bruto DESC
        """,
        top, *params,
    )
    return _rows_to_list(cur)

