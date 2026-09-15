"""
registro_descartes.py — Registro auditável de descartes e avisos do pipeline.

Cada ocorrência vira uma linha JSON (JSON Lines) em logs/, com etapa, estado, motivo e detalhe,
substituindo o descarte silencioso por um rastro que pode ser contado e inspecionado depois.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"


class RegistroDescartes:
    """Acumula ocorrências de uma execução e as grava em logs/<etapa>_<timestamp>.jsonl."""

    DESCARTE = "descarte"   # registro não segue adiante no pipeline
    AVISO    = "aviso"      # registro segue, mas com inconsistência que merece inspeção

    def __init__(self, etapa: str, pasta: Path = LOG_DIR):
        self.etapa = etapa
        self.pasta = pasta
        self.inicio = datetime.now()
        self._ocorrencias: list[dict] = []

    def registrar(self, estado: str, motivo: str, detalhe: dict | None = None, gravidade: str = DESCARTE) -> None:
        self._ocorrencias.append({
            "etapa": self.etapa,
            "gravidade": gravidade,
            "estado": estado,
            "motivo": motivo,
            "detalhe": detalhe or {},
        })

    def aviso(self, estado: str, motivo: str, detalhe: dict | None = None) -> None:
        self.registrar(estado, motivo, detalhe, self.AVISO)

    def contagem(self, estado: str | None = None) -> Counter:
        """Quantidade por (gravidade, motivo), opcionalmente de um único estado."""
        return Counter(
            (o["gravidade"], o["motivo"]) for o in self._ocorrencias
            if estado is None or o["estado"] == estado
        )

    def salvar(self) -> Path | None:
        if not self._ocorrencias:
            return None
        self.pasta.mkdir(exist_ok=True)
        caminho = self.pasta / f"{self.etapa}_{self.inicio:%Y%m%d_%H%M%S}.jsonl"
        with open(caminho, "w", encoding="utf-8") as f:
            for ocorrencia in self._ocorrencias:
                f.write(json.dumps(ocorrencia, ensure_ascii=False, default=str) + "\n")
        return caminho

    def imprimir_resumo(self) -> None:
        por_estado = Counter((o["estado"], o["gravidade"], o["motivo"]) for o in self._ocorrencias)
        if not por_estado:
            print(f"[{self.etapa}] Nenhum descarte ou aviso registrado.")
            return
        print(f"\n[{self.etapa}] Descartes e avisos:")
        for (estado, gravidade, motivo), qtd in sorted(por_estado.items()):
            print(f"  {estado}  {gravidade:<8} {motivo:<40} {qtd:>8,}")
