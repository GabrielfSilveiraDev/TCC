"""
load_data.py — Carrega os JSONs normalizados no SQL Server.

Uso:
    python load_data.py [--estado ES] [--batch 500]

Chave natural: (estado, matrícula, ano, mês, folha). Registros já presentes no banco não são
reinseridos; ocorrências (já carregados, estado desconhecido, erro de lote) vão para logs/carga_*.jsonl.

Conexão configurada em settings.py (arquivo .env / variáveis DB_SERVER, DB_NAME,
DB_USER, DB_PASSWORD; DB_USER vazio usa autenticação do Windows).
"""

import json
import argparse
from collections import Counter
from pathlib import Path
from typing import Optional

import pyodbc

from registro_descartes import RegistroDescartes
from settings import get_database_settings

NORMALIZED_DIR = Path(__file__).parent / "Dados_Normalizados"


def get_connection() -> pyodbc.Connection:
    return pyodbc.connect(get_database_settings().connection_string(), autocommit=False)


def get_estado_map(cur: pyodbc.Cursor) -> dict[str, int]:
    cur.execute("SELECT sigla, estado_id FROM dbo.dim_estado")
    return {row[0]: row[1] for row in cur.fetchall()}


def upsert_cargos(cur: pyodbc.Cursor, descricoes: set[str]) -> dict[str, int]:
    if not descricoes:
        return {}

    existing: dict[str, int] = {}
    cur.execute("SELECT descricao, cargo_id FROM dbo.dim_cargo")
    for row in cur.fetchall():
        existing[row[0]] = row[1]

    novos = [d for d in descricoes if d not in existing]
    if novos:
        cur.executemany(
            "INSERT INTO dbo.dim_cargo (descricao) VALUES (?)",
            [(d,) for d in novos],
        )
        cur.connection.commit()
        cur.execute("SELECT descricao, cargo_id FROM dbo.dim_cargo")
        existing = {row[0]: row[1] for row in cur.fetchall()}

    return existing


def get_existing_keys(cur: pyodbc.Cursor, estado_id: int) -> set[tuple]:
    cur.execute(
        "SELECT matricula, ano, mes, folha FROM dbo.fato_remuneracao WITH (NOLOCK) WHERE estado_id = ?",
        estado_id,
    )
    return {(r[0], r[1], r[2], r[3]) for r in cur.fetchall()}


def load_records(records: list[dict], conn: pyodbc.Connection, estado_id_map: dict,
                 registro: RegistroDescartes, batch_size: int = 5000) -> tuple[int, int]:
    if not records:
        return 0, 0
    cur = conn.cursor()
    sigla = records[0].get("estado", "")

    descricoes = {r.get("cargo") for r in records if r.get("cargo")}
    cargo_map = upsert_cargos(cur, descricoes)

    estado_id = estado_id_map.get(sigla)
    existing_keys = get_existing_keys(cur, estado_id) if estado_id is not None else set()

    rows_to_insert = []
    ocorrencias = Counter()

    for rec in records:
        est_id = estado_id_map.get(rec.get("estado", ""))
        if est_id is None:
            ocorrencias["estado_desconhecido"] += 1
            continue
        if not rec.get("matricula"):
            ocorrencias["sem_matricula"] += 1
            continue

        chave = (rec["matricula"], rec["ano"], rec["mes"], rec["folha"])
        if chave in existing_keys:
            ocorrencias["ja_carregado"] += 1
            continue
        existing_keys.add(chave)

        cargo_desc = rec.get("cargo")
        rows_to_insert.append((
            est_id,
            cargo_map.get(cargo_desc) if cargo_desc else None,
            rec["matricula"],
            rec.get("nome"),
            rec.get("lotacao"),
            rec.get("situacao"),
            rec["mes"],
            rec["ano"],
            rec["folha"],
            rec["tipo_folha"],
            rec.get("folha_origem"),
            float(rec.get("salario_base") or 0),
            float(rec.get("beneficios")   or 0),
            float(rec.get("descontos")    or 0),
        ))

    # Ocorrências esperadas em recargas são registradas de forma agregada.
    for motivo, qtd in ocorrencias.items():
        registro.registrar(sigla, motivo, {"quantidade": qtd})

    sql = """
        INSERT INTO dbo.fato_remuneracao
            (estado_id, cargo_id, matricula, nome, lotacao, situacao,
             mes, ano, folha, tipo_folha, folha_origem,
             salario_base, beneficios, descontos)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    ok = 0
    erros = 0
    for i in range(0, len(rows_to_insert), batch_size):
        lote = rows_to_insert[i: i + batch_size]
        try:
            cur.fast_executemany = True
            cur.executemany(sql, lote)
            conn.commit()
            ok += len(lote)
        except pyodbc.Error as exc:
            conn.rollback()
            erros += len(lote)
            registro.registrar(sigla, "erro_insercao_lote", {"lote": i // batch_size + 1, "registros": len(lote), "erro": str(exc)})
            print(f"  [ERRO lote {i // batch_size + 1}] {exc}")

        done = min(i + batch_size, len(rows_to_insert))
        print(f"  Lote {i // batch_size + 1}: {done}/{len(rows_to_insert)} inseridos")

    if ocorrencias:
        print(f"  Não inseridos: {dict(ocorrencias)}")

    return ok, erros


def run(estado: Optional[str] = None, batch_size: int = 5000) -> None:
    if estado:
        arquivos = [NORMALIZED_DIR / f"remuneracoes_{estado.lower()}.json"]
    else:
        arquivos = sorted(NORMALIZED_DIR.glob("remuneracoes_??.json"))

    registro = RegistroDescartes("carga")
    conn = get_connection()
    cur  = conn.cursor()
    estado_id_map = get_estado_map(cur)

    total_ok = 0
    total_erros = 0

    for arquivo in arquivos:
        if not arquivo.exists():
            print(f"[AVISO] Arquivo não encontrado: {arquivo}")
            registro.registrar(arquivo.stem[-2:].upper(), "arquivo_normalizado_ausente", {"arquivo": str(arquivo)})
            continue

        print(f"\nCarregando: {arquivo.name}")
        with open(arquivo, encoding="utf-8") as f:
            records = json.load(f)

        ok, erros = load_records(records, conn, estado_id_map, registro, batch_size)
        print(f"  Ok: {ok:,}  Erros: {erros:,}")
        total_ok    += ok
        total_erros += erros

    conn.close()
    print(f"\nConcluído. Total inserido: {total_ok:,}  Erros: {total_erros:,}")
    registro.imprimir_resumo()
    caminho_log = registro.salvar()
    if caminho_log:
        print(f"Log da carga: {caminho_log}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga dos dados normalizados no SQL Server")
    parser.add_argument("--estado", help="Sigla do estado (ex: ES). Omitir para carregar todos.")
    parser.add_argument("--batch",  type=int, default=5000, help="Tamanho do lote (default 5000)")
    args = parser.parse_args()
    run(estado=args.estado, batch_size=args.batch)
