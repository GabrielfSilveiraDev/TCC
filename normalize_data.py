"""
normalize_data.py — Normalização dos JSONs de cada estado para o schema canônico.

Saída por registro:
    estado, matricula, nome, cargo, lotacao, situacao, mes, ano,
    salario_base, beneficios, descontos, salario_bruto, salario_liquido

Uso:
    python normalize_data.py
Gera:
    Dados_Normalizados/remuneracoes_<ESTADO>.json
    Dados_Normalizados/remuneracoes_consolidado.json
"""

import os
import re
import json
import glob
from pathlib import Path

BASE_DIR   = Path(__file__).parent / "Scrapers"
OUTPUT_DIR = Path(__file__).parent / "Dados_Normalizados"
OUTPUT_DIR.mkdir(exist_ok=True)


def _parse_brl(value) -> float:
    """Converte qualquer representação monetária em float."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    text = re.sub(r"R\$\s*", "", text)
    text = text.replace(" ", "").replace("\xa0", "")
    negative = text.startswith("-")
    text = text.lstrip("-").replace(".", "").replace(",", ".")
    try:
        result = float(text)
        return -result if negative else result
    except ValueError:
        return 0.0


def _normalize_situacao(raw: str) -> str:
    if not raw:
        return "Desconhecido"
    raw_lower = raw.strip().lower()
    if any(k in raw_lower for k in ("ativo", "active")):
        return "Ativo"
    if any(k in raw_lower for k in ("inativo", "reformado", "aposentado", "pensionista")):
        return "Inativo/Aposentado"
    return raw.strip().title()


def _mes_por_nome(nome: str) -> int:
    meses = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
        "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
        "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    }
    return meses.get(nome.strip().lower(), 0)


def _mes_ano_to_int(mes_ano: str):
    """'01/2024' → (1, 2024). Retorna (0, 0) se inválido."""
    try:
        parts = mes_ano.strip().split("/")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 0, 0


_KEYWORDS_SALARIO = re.compile(
    r"vencimento|subsid|salari|ordenado|remuneracao|remuneração|piso|"
    r"cargo em comiss[aã]o|cargo efetivo|tabela vencimento",
    re.IGNORECASE,
)

def _classify_credito(descricao: str) -> str:
    if _KEYWORDS_SALARIO.search(str(descricao)):
        return "salario_base"
    return "beneficios"


def _parse_es(records: list) -> list:
    out = []
    for r in records:
        financeiro = r.get("financeiro", {})
        creditos   = financeiro.get("creditos", [])
        descontos  = financeiro.get("descontos", [])

        sal_base   = sum(_parse_brl(c["valor"]) for c in creditos
                         if _classify_credito(c.get("descricao", "")) == "salario_base")
        beneficios = sum(_parse_brl(c["valor"]) for c in creditos
                         if _classify_credito(c.get("descricao", "")) == "beneficios")
        total_desc = sum(abs(_parse_brl(d["valor"])) for d in descontos)

        bruto   = sal_base + beneficios
        liquido = bruto - total_desc

        mes = r.get("mes") or _mes_ano_to_int(r.get("mes_ano", ""))[0]
        ano = r.get("ano") or _mes_ano_to_int(r.get("mes_ano", ""))[1]

        out.append({
            "estado": "ES",
            "matricula": str(r.get("matricula", "") or ""),
            "nome": (r.get("nome") or "").strip().title(),
            "cargo": (r.get("cargo") or "").strip().title(),
            "lotacao": (r.get("lotacao") or "").strip(),
            "situacao": _normalize_situacao(r.get("situacao", "")),
            "mes": mes, "ano": ano,
            "salario_base": round(sal_base, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


def _parse_sp(records: list) -> list:
    out = []
    for r in records:
        proventos  = r.get("proventos", [])

        # Usar campos pré-calculados do JSON
        # salario_liquido já considera TODOS os proventos (inclusive Auxilios, etc.)
        # total_descontos é negativo no JSON
        total_desc = abs(_parse_brl(r.get("total_descontos", 0)))
        liquido    = _parse_brl(r.get("salario_liquido", 0))
        # bruto = liquido + descontos = soma real de todos os proventos
        bruto      = round(liquido + total_desc, 2)

        # Salario_base: itens classificados como base no array de proventos
        sal_base   = sum(_parse_brl(p["valor"]) for p in proventos
                         if _classify_credito(p.get("descricao", "")) == "salario_base")
        beneficios = round(bruto - sal_base, 2)

        mes, ano = _mes_ano_to_int(r.get("mes_ano", ""))

        out.append({
            "estado": "SP",
            "matricula": str(r.get("matricula", "") or ""),
            "nome": (r.get("nome") or "").strip().title(),
            "cargo": (r.get("cargo") or "").strip().title(),
            "lotacao": (r.get("lotacao") or "").strip(),
            "situacao": _normalize_situacao(r.get("tipo", "")),
            "mes": mes, "ano": ano,
            "salario_base": round(sal_base, 2),
            "beneficios": beneficios,
            "descontos": round(total_desc, 2),
            "salario_bruto": bruto,
            "salario_liquido": round(liquido, 2),
        })
    return out


def _parse_mg(records: list) -> list:
    out = []
    for r in records:
        mes_nome = r.get("MÊS REFERÊNCIA", r.get("MŠS REFERŠNCIA", ""))
        mes = _mes_por_nome(mes_nome)

        cargo = (
            r.get("NOME DO CARGO / FUNÇÃO PÚBLICA / EMPREGO PÚBLICO")
            or r.get("NOME DO CARGO / FUN\u00c7\u00c3O P\u00dablica / EMPREGO P\u00daBlico")
            or r.get("NOME DO CARGO / FUN‡ƒO PšBLICA / EMPREGO PšBLICO", "")
        )
        situacao = (
            r.get("SITUAÇÃO DO SERVIDOR")
            or r.get("SITUA\u00c7\u00c3O DO SERVIDOR")
            or r.get("SITUA‡ƒO DO SERVIDOR", "")
        )

        out.append({
            "estado": "MG",
            "matricula": None,
            "nome": None,
            "cargo": (cargo or "").strip().title(),
            "lotacao": None,
            "situacao": _normalize_situacao(situacao),
            "mes": mes, "ano": 0,
            "salario_base": 0.0, "beneficios": 0.0, "descontos": 0.0,
            "salario_bruto": 0.0, "salario_liquido": 0.0,
        })
    return out


def _parse_rs(records: list) -> list:
    out = []
    for r in records:
        sal_base   = _parse_brl(r.get("remuneracao_bruta", 0))
        beneficios = (
            _parse_brl(r.get("parcelas_indenizatorias", 0))
            + _parse_brl(r.get("abono_permanencia", 0))
            + _parse_brl(r.get("terco_ferias", 0))
            + _parse_brl(r.get("gratificacao_natalina", 0))
        )
        total_desc = abs(_parse_brl(r.get("descontos_legais", 0)))
        bruto   = sal_base + beneficios
        liquido = bruto - total_desc
        mes, ano = _mes_ano_to_int(r.get("mes_ano", ""))

        out.append({
            "estado": "RS",
            "matricula": None,
            "nome": (r.get("nome") or r.get("nome_servidor") or "").strip().title(),
            "cargo": (r.get("cargo") or "").strip().title(),
            "lotacao": (r.get("funcao_gratificada") or "").strip(),
            "situacao": "Desconhecido",
            "mes": mes, "ano": ano,
            "salario_base": round(sal_base, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


def _parse_pr(records: list) -> list:
    out = []
    for r in records:
        fin = r.get("financeiro", {})

        def _sum(fin_dict, *partials) -> float:
            """Soma TODOS os valores cujas chaves contenham qualquer dos partials."""
            total = 0.0
            for key, val in fin_dict.items():
                for p in partials:
                    if p.lower() in key.lower():
                        total += _parse_brl(val)
                        break
            return total

        # Usar Total Bruto pré-calculado como fonte de verdade
        bruto    = _sum(fin, "total bruto")

        # Salário base = componentes fixos/permanentes
        sal_base = _sum(fin, "vantagens fixas", "vantagens pessoais", "cargo em comiss")

        # Benefícios = tudo que não é sal_base nem desconto
        beneficios = round(bruto - sal_base, 2)

        # Descontos (ambos negativos no JSON, usar abs)
        total_desc = (
            abs(_sum(fin, "descontos obrig"))
            + abs(_sum(fin, "redutor constitucional"))
        )
        liquido = round(bruto - total_desc, 2)

        periodo = r.get("periodo_folha", "")
        try:
            ano_str, mes_str = periodo.split(".")[0], periodo.split(".")[1][:2]
            ano = int(ano_str)
            mes = int(mes_str)
        except Exception:
            mes, ano = 0, 0

        matricula = str(fin.get("MATRICULA") or fin.get("MATR\u00cdCULA") or "").strip()
        cargo = str(
            fin.get("CARGO")
            or fin.get("Cargo em Comiss\u00e3o / Fun\u00e7\u00e3o")
            or fin.get("Cargo em Comisso / Funo", "")
        ).strip().title()
        if cargo.lower() == "null":
            cargo = str(
                fin.get("Cargo em Comissão / Função")
                or fin.get("Cargo em Comisso / Funo", "")
            ).strip().title()
        lotacao = str(
            fin.get("LOTAÇÃO") or fin.get("LOTA\u00c7\u00c3O") or fin.get("LOTA‡ƒO", "")
        ).strip()

        out.append({
            "estado": "PR",
            "matricula": matricula,
            "nome": (r.get("nome") or "").strip().title(),
            "cargo": cargo,
            "lotacao": lotacao,
            "situacao": _normalize_situacao(r.get("natureza_detalhada", "")),
            "mes": mes, "ano": ano,
            "salario_base": round(sal_base, 2),
            "beneficios": beneficios,
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": liquido,
        })
    return out


def _parse_sc(records: list) -> list:
    out = []
    for r in records:
        detalhes  = r.get("Detalhes_Remuneracao", {})
        proventos = detalhes.get("proventos", [])
        descontos = detalhes.get("descontos", [])

        sal_base   = sum(_parse_brl(p["valor"]) for p in proventos
                         if _classify_credito(p.get("descricao", "")) == "salario_base")
        beneficios = sum(_parse_brl(p["valor"]) for p in proventos
                         if _classify_credito(p.get("descricao", "")) == "beneficios")
        total_desc = sum(abs(_parse_brl(d["valor"])) for d in descontos)

        bruto   = sal_base + beneficios
        liquido = bruto - total_desc

        tipo_folha = r.get("Tipo_Folha", "")
        match = re.search(r"(\d{2})/(\d{4})", tipo_folha)
        if match:
            mes, ano = int(match.group(1)), int(match.group(2))
        else:
            parts = r.get("ID_Servidor_Completo", "").split("##")
            try:
                mes, ano = int(parts[1]), int(parts[2])
            except Exception:
                mes, ano = 0, 0

        matricula_parts = r.get("ID_Servidor_Completo", "").split("##")
        matricula = matricula_parts[0] if matricula_parts else None

        out.append({
            "estado": "SC",
            "matricula": matricula,
            "nome": (r.get("Nome") or "").strip().title(),
            "cargo": (r.get("Cargo_Principal") or "").strip().title(),
            "lotacao": None,
            "situacao": _normalize_situacao(r.get("situacao", "")),
            "mes": mes, "ano": ano,
            "salario_base": round(sal_base, 2),
            "beneficios": round(beneficios, 2),
            "descontos": round(total_desc, 2),
            "salario_bruto": round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


def _parse_rj(records: list) -> list:
    out = []
    for r in records:
        remuneracao = r.get("remuneracao", {})

        def _get_val(partial: str) -> float:
            """Retorna o primeiro valor cujo chave contenha partial (case-insensitive)."""
            for key, val in remuneracao.items():
                if partial.lower() in key.lower():
                    return _parse_brl(val)
            return 0.0

        # salario_base = apenas a remuneração do cargo efetivo (fixo permanente)
        sal_base   = _get_val("cargo efetivo")
        # bruto = total bruto pré-calculado (fonte de verdade)
        bruto      = _get_val("total bruto") or round(sal_base, 2)
        # beneficios = tudo no bruto que não é salário base
        # (outras verbas, função gratificada, cargo em comissão, indenizações, etc.)
        beneficios = round(bruto - sal_base, 2)
        # descontos = total descontos pré-calculado (fonte de verdade)
        total_desc = abs(_get_val("total descontos"))
        # liquido = total líquido pré-calculado; fallback = bruto - descontos
        liquido    = _get_val("total liquido") or round(bruto - total_desc, 2)

        try:
            partes = r.get("mes_ano", "").split("-")
            mes = int(partes[0].strip())
            ano = int(partes[1].strip())
        except Exception:
            mes, ano = 0, 0

        out.append({
            "estado":          "RJ",
            "matricula":       str(r.get("matricula", "") or ""),
            "nome":            (r.get("nome") or "").strip().title(),
            "cargo":           (r.get("cargo") or "").strip().title(),
            "lotacao":         (r.get("localizacao") or "").strip(),
            "situacao":        "Desconhecido",
            "mes":             mes,
            "ano":             ano,
            "salario_base":    round(sal_base, 2),
            "beneficios":      beneficios,
            "descontos":       round(total_desc, 2),
            "salario_bruto":   round(bruto, 2),
            "salario_liquido": round(liquido, 2),
        })
    return out


ESTADO_CONFIG = {
    "ES": {"pasta": "Dados_ES", "parser": _parse_es, "pattern": "tce_es_*.json"},
    "SP": {"pasta": "Dados_SP", "parser": _parse_sp, "pattern": "tce_sp_*.json"},
    "MG": {"pasta": "Dados_MG", "parser": _parse_mg, "pattern": "tce_mg_*.json"},
    "RS": {"pasta": "Dados_RS", "parser": _parse_rs, "pattern": "tce_rs_*.json"},
    "PR": {"pasta": "Dados_PR", "parser": _parse_pr, "pattern": "tce_pr_*.json"},
    "SC": {"pasta": "Dados_SC", "parser": _parse_sc, "pattern": "tce_sc_*.json"},
    "RJ": {"pasta": "Dados_RJ", "parser": _parse_rj, "pattern": "tce_rj_*.json"},
}

_FILE_YEAR_RE = re.compile(r"_(\d{4})\.json$")

def _extract_year_from_filename(path: str) -> int:
    m = _FILE_YEAR_RE.search(path)
    return int(m.group(1)) if m else 0


def normalize_estado(estado: str) -> list:
    cfg     = ESTADO_CONFIG[estado]
    pasta   = BASE_DIR / cfg["pasta"]
    parser  = cfg["parser"]
    pattern = str(pasta / cfg["pattern"])

    arquivos = sorted(glob.glob(pattern))
    if not arquivos:
        print(f"  [AVISO] Nenhum arquivo encontrado em {pasta}")
        return []

    all_records = []
    for filepath in arquivos:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  [ERRO] JSON inválido em {filepath}: {e}")
            continue

        if not isinstance(raw, list):
            raw = [raw]

        parsed = parser(raw)

        file_year = _extract_year_from_filename(filepath)
        for rec in parsed:
            if rec["ano"] == 0 and file_year:
                rec["ano"] = file_year

        all_records.extend(parsed)
        print(f"  ✓ {os.path.basename(filepath)}: {len(parsed):,} registros")

    return all_records


def run():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    todos = []
    for estado in ESTADO_CONFIG:
        print(f"\n-- Processando {estado} --")
        registros = normalize_estado(estado)
        todos.extend(registros)

        out_file = OUTPUT_DIR / f"remuneracoes_{estado.lower()}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(registros, f, ensure_ascii=False, indent=2)
        print(f"  -> Salvo: {out_file.name}  ({len(registros):,} registros)")

    consolidado = OUTPUT_DIR / "remuneracoes_consolidado.json"
    with open(consolidado, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

    print(f"\nTOTAL CONSOLIDADO: {len(todos):,} registros")
    print(f"Arquivo: {consolidado}")


if __name__ == "__main__":
    run()

