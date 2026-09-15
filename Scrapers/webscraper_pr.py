from base_scraper import RequestsScraper
from datetime import datetime
import re
import time


class ColetaIncompletaError(RuntimeError):
    """A quantidade de registros obtida difere da informada pela própria API."""


class ScraperPR(RequestsScraper):
    """
    Coletor do TCE-PR baseado na API JSON pública consumida pelo portal de transparência.

    Segue as decisões adotadas no coletor do TCE-RJ:
      - identifica o servidor pela matrícula, e não pelo nome;
      - só marca um período como processado quando todas as naturezas foram coletadas
        por completo (contagem conferida contra o dataCount da API);
      - preserva cada folha publicada (ordinária, suplementares, parcelas do 13º) como
        período distinto, sem colapsá-las na competência.
    """

    URL_PORTAL   = "https://www.tce.pr.gov.br/transparencia-do-tce-pr/pessoal/remuneracao.htm"
    URL_API      = "https://www.tce.pr.gov.br/proxy/remuneracoes/api/remuneracoes"
    URL_LEGENDAS = "https://www.tce.pr.gov.br/api/remuneracoes/legendas"

    _RE_COMPETENCIA = re.compile(r"^(\d{4})\.(\d{2})")
    _RE_VALOR       = re.compile(r"^(-)?\s*R\$\s*([\d.]+,\d{2})$")
    _RE_DATA        = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}$")
    _RE_TRACO       = re.compile(r"^(R\$)?\s*-$")          # formato contábil de planilha para zero
    _RE_RUBRICA     = re.compile(r"\[\d+\]$")              # rubricas monetárias trazem o índice [n]

    # A API serializa alguns valores monetários como data (número de série do Excel,
    # época 30/12/1899). A data 31/12/1899 00:00:00 representa valor zero; as demais
    # equivalem ao número de dias desde a época. Regra verificada contra o Total Bruto.
    _EPOCA_EXCEL = datetime(1899, 12, 30)
    _DATA_ZERO   = "31/12/1899 00:00:00"

    def __init__(self, ano_limite=2020, tamanho_pagina=500, pausa_segundos=0.5):
        super().__init__("TCE-PR", "Dados_PR")
        self.ano_limite = ano_limite
        self.tamanho_pagina = tamanho_pagina
        self.pausa_segundos = pausa_segundos
        self.session.headers.update({"Referer": self.URL_PORTAL, "Accept": "application/json"})

    # ------------------------------------------------------------------
    # Acesso à API
    # ------------------------------------------------------------------

    def _get(self, url, **params):
        resposta = self.session.get(url, params=params, timeout=90)
        resposta.raise_for_status()
        time.sleep(self.pausa_segundos)
        if resposta.status_code == 204 or not resposta.content:
            return {"data": [], "dataCount": 0}
        corpo = resposta.json()
        if isinstance(corpo, dict) and corpo.get("status", "SUCCESS") != "SUCCESS":
            raise RuntimeError(f"API retornou {corpo.get('status')}: {corpo.get('message')}")
        return corpo

    def _competencia(self, periodo):
        """'2025.12 Suplementar I' → ('2025', '12')."""
        m = self._RE_COMPETENCIA.match(periodo)
        if not m:
            raise ValueError(f"Período com formato inesperado: {periodo!r}")
        return m.group(1), m.group(2)

    def _valor(self, texto):
        """
        Converte 'R$ 1.234,56' ou '-R$ 1.234,56' em float. Aceita também o valor serializado como
        data e o traço contábil de zero. Retorna (valor, formato): formato é 'moeda', 'data' ou 'traco';
        qualquer outro texto gera erro.
        """
        texto = str(texto).strip()
        m = self._RE_VALOR.match(texto)
        if m:
            numero = float(m.group(2).replace(".", "").replace(",", "."))
            return (-numero if m.group(1) else numero), "moeda"
        if self._RE_TRACO.match(texto):
            return 0.0, "traco"
        if self._RE_DATA.match(texto):
            if texto == self._DATA_ZERO:
                return 0.0, "data"
            dias = (datetime.strptime(texto, "%d/%m/%Y %H:%M:%S") - self._EPOCA_EXCEL).total_seconds() / 86400
            return round(dias, 2), "data"
        raise ValueError(f"Valor monetário com formato inesperado: {texto!r}")

    def _financeiro(self, grid):
        """
        Converte o grid em rubricas monetárias e atributos descritivos (como LOTAÇÃO e CARGO, que a API
        passou a incluir no grid). Um campo só é atributo se o título não tiver índice [n] E o valor não
        for monetário — há rubricas publicadas sem índice (ex.: 'Funções e Encargos Especiais').
        Guarda o texto original dos valores convertidos de data ou traço e lista os campos sem valor.
        """
        financeiro, atributos, convertidos, ausentes = {}, {}, {}, []
        for campo in grid:
            titulo, valor = campo["titulo"].strip(), campo.get("valor")
            if valor is None:
                financeiro[titulo] = None
                ausentes.append(titulo)
                continue
            try:
                financeiro[titulo], formato = self._valor(valor)
            except ValueError:
                if self._RE_RUBRICA.search(titulo):
                    raise
                atributos[titulo] = valor.strip()
                continue
            if formato != "moeda":
                convertidos.setdefault(formato, {})[titulo] = valor
        return financeiro, atributos, convertidos, ausentes

    # ------------------------------------------------------------------
    # Coleta
    # ------------------------------------------------------------------

    def _salvar_legendas(self, naturezas):
        """Guarda as notas explicativas das rubricas [1]..[12] de cada natureza."""
        legendas = {}
        for natureza in naturezas:
            try:
                legendas[natureza] = self._get(f"{self.URL_LEGENDAS}/{natureza}")
            except Exception as erro:
                self.log(f"  Legendas indisponíveis para {natureza}: {erro}")
        self.save_data(legendas, "legendas.json")

    def _coletar_natureza(self, periodo, natureza):
        itens, pagina, total = [], 1, None
        while True:
            corpo = self._get(self.URL_API, limit=self.tamanho_pagina, page=pagina, ordered="true",
                              mesAno=periodo, natureza=natureza["valor"])
            lote = corpo.get("data") or []
            total = corpo.get("dataCount", len(lote)) if total is None else total
            itens.extend(lote)
            if not lote or len(itens) >= total:
                break
            pagina += 1

        if len(itens) != total:
            raise ColetaIncompletaError(
                f"{periodo} / {natureza['descricao']}: {len(itens)} registros obtidos, API informa {total}"
            )

        registros = []
        for item in itens:
            financeiro, atributos, convertidos, ausentes = self._financeiro(item.get("detalhesGrid") or [])
            registro = {
                "periodo_folha":      periodo,
                "natureza":           natureza["valor"],
                "natureza_descricao": natureza["descricao"],
                "matricula":          item.get("matricula"),
                "nome":               item.get("nome"),
                "cargo":              item.get("cargo") or atributos.get("CARGO"),
                "cargo_comissionado": item.get("cargoComissionado"),
                "lotacao":            item.get("lotacao") or atributos.get("LOTAÇÃO"),
                "financeiro":         financeiro,
            }
            if "data" in convertidos:
                registro["valores_originais_em_data"] = convertidos["data"]
            if "traco" in convertidos:
                registro["valores_originais_em_traco"] = convertidos["traco"]
            if ausentes:
                registro["valores_ausentes"] = ausentes
            registros.append(registro)
        return registros

    def _coletar_periodo(self, periodo):
        naturezas = self._get(f"{self.URL_API}/naturezas", mesAno=periodo).get("data") or []
        registros = []
        for natureza in naturezas:
            lote = self._coletar_natureza(periodo, natureza)
            self.log(f"  {periodo} / {natureza['descricao']}: {len(lote)} registros")
            registros.extend(lote)
        return registros, naturezas

    def scrape(self):
        progresso = self._load_progress()
        processados = set(progresso.get("processed_periods", []))

        periodos = [p["valor"] for p in self._get(f"{self.URL_API}/mes-ano").get("data") or []]
        pendentes = sorted(
            p for p in periodos
            if int(self._competencia(p)[0]) >= self.ano_limite and p not in processados
        )
        self.log(f"Períodos na API: {len(periodos)}. Pendentes a partir de {self.ano_limite}: {len(pendentes)}")

        falhas, naturezas_vistas = [], set()
        for periodo in pendentes:
            try:
                registros, naturezas = self._coletar_periodo(periodo)
            except Exception as erro:
                # Padrão do TCE-RJ: período com falha não é marcado e será retomado na próxima execução.
                self.log(f"[FALHA] {periodo}: {type(erro).__name__}: {erro}. Período não marcado como processado.")
                falhas.append(periodo)
                continue

            naturezas_vistas.update(n["valor"] for n in naturezas)
            ano, mes = self._competencia(periodo)
            self.save_data_merge(registros, f"tce_pr_{mes}_{ano}.json", ["matricula", "periodo_folha", "natureza"])
            processados.add(periodo)
            self._save_progress({"processed_periods": sorted(processados)})

        if naturezas_vistas:
            self._salvar_legendas(sorted(naturezas_vistas))

        self.log(f"Concluído: {len(pendentes) - len(falhas)} período(s) coletado(s), {len(falhas)} com falha.")
        if falhas:
            raise ColetaIncompletaError(f"Períodos com falha (serão retomados): {falhas}")


if __name__ == "__main__":
    scraper = ScraperPR()
    scraper.run()
