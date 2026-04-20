from base_scraper import RequestsScraper
from bs4 import BeautifulSoup
from datetime import datetime
import requests
import time

class ScraperSP(RequestsScraper):
    def __init__(self):
        super().__init__("TCE-SP", "Dados_SP")
        self.url_base = "https://www.tce.sp.gov.br/transparencia-tcesp/gestao-pessoas/remuneracao/tabela"
        self.mapa_anos = {
            2026: 1,
            2025: 2,
            2024: 3,
            2023: 4,
            2022: 5,
            2021: 6
        }
        self.situacoes = {
            1: "ATIVO",
            2: "INATIVO"
        }
        self.identificacoes = {
            1: "Servidor",
            2: "Membro",
            3: "Residente-Bolsista"
        }

    def _buscar_dados_mes(self, ano_rotulo, ano_id, mes):
        dados_mes = []
        for cod_situacao, nome_situacao in self.situacoes.items():
            for cod_id, nome_id in self.identificacoes.items():
                self.log(f"Processando: {nome_situacao} / {nome_id}...")
                pagina = 1
                while True:
                    parametros = {
                        "vencimentos_ano": ano_id,
                        "Mes": mes,
                        "Situacao": cod_situacao,
                        "Nome": "",
                        "Identificacao": cod_id,
                        "page": pagina
                    }
                    try:
                        resposta = self.session.get(self.url_base, params=parametros, timeout=30)
                        resposta.raise_for_status()
                    except requests.exceptions.ConnectionError as e:
                        self.log(f"Erro de conexao (Pagina {pagina}): {e}. Aguardando 30s...")
                        time.sleep(30)
                        continue
                    except Exception as e:
                        self.log(f"Erro na requisicao (Pagina {pagina}): {e}")
                        break
                    sopa = BeautifulSoup(resposta.text, "html.parser")
                    tabela = sopa.select_one("div.table-responsive table.table-hover.table-striped tbody")
                    if not tabela:
                        break
                    linhas = tabela.find_all("tr")
                    if not linhas:
                        break
                    for tr in linhas:
                        td = tr.find_all("td")
                        if len(td) < 21:
                            continue
                        matricula = td[2].text.strip()
                        nome = td[3].text.strip()
                        cargo = td[20].text.strip()
                        lotacao = td[21].text.strip() if len(td) > 21 else ''
                        proventos_brutos = [
                            ("Vencimentos", td[5].text.strip()),
                            ("Vantagens Pessoais", td[6].text.strip()),
                            ("Outras Verbas", td[7].text.strip()),
                            ("Eventuais", td[11].text.strip()),
                            ("Abono Permanencia", td[12].text.strip()),
                            ("Auxilios", td[13].text.strip()),
                            ("1/3 Ferias", td[14].text.strip()),
                            ("13 Salario", td[16].text.strip()),
                            ("13 Abono", td[17].text.strip()),
                        ]
                        proventos = [{"descricao": desc, "valor": val} for desc, val in proventos_brutos if self.limpar_numero_br(val) != 0]
                        descontos_brutos = [
                            ("Redutor", td[8].text.strip()),
                            ("Descontos Legais", td[10].text.strip()),
                            ("Desconto Ferias", td[15].text.strip()),
                            ("Desconto 13", td[18].text.strip()),
                        ]
                        descontos = [{"descricao": desc, "valor": val} for desc, val in descontos_brutos if self.limpar_numero_br(val) != 0]
                        total_prov = td[9].text.strip()
                        sal_liq = td[19].text.strip()
                        total_desc_float = sum(self.limpar_numero_br(d["valor"]) for d in descontos)
                        total_desc_str = f"{total_desc_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        obj_servidor = {
                            "matricula": matricula,
                            "nome": nome,
                            "cargo": cargo,
                            "lotacao": lotacao,
                            "mes_ano": f"{mes:02d}/{ano_rotulo}",
                            "tipo": nome_situacao,
                            "identificacao": nome_id,
                            "proventos": proventos,
                            "descontos": descontos,
                            "total_proventos": total_prov,
                            "total_descontos": total_desc_str,
                            "salario_liquido": sal_liq,
                            "url_origem": resposta.url
                        }
                        dados_mes.append(obj_servidor)
                    link_prox_pagina = sopa.find("a", {"rel": "next"})
                    if not link_prox_pagina:
                        break
                    pagina += 1
                    time.sleep(0.1)
        return dados_mes

    def scrape(self):
        progress = self._load_progress()
        last_processed_year = progress.get('year', 0)
        last_processed_month = progress.get('month', 0)

        sorted_years = sorted(self.mapa_anos.items(), key=lambda item: item[0], reverse=True)
        now = datetime.now()

        for ano_rotulo, ano_id in sorted_years:
            if last_processed_year > 0 and ano_rotulo > last_processed_year:
                continue

            start_month = 1
            if ano_rotulo == last_processed_year:
                start_month = last_processed_month + 1

            ultimo_mes = now.month if ano_rotulo == now.year else 12
            
            for mes in range(start_month, ultimo_mes + 1):
                self.log(f"Iniciando extracao: {mes:02d}/{ano_rotulo} (ID Ano: {ano_id})")
                dados = self._buscar_dados_mes(ano_rotulo, ano_id, mes)
                
                if not dados:
                    self.log(f"Nenhum dado encontrado para {mes:02d}/{ano_rotulo}.")
                else:
                    nome_arquivo = f"tce_sp_{mes:02d}_{ano_rotulo}.json"
                    self.save_data(dados, nome_arquivo)
                
                self._save_progress({'year': ano_rotulo, 'month': mes})
                time.sleep(0.5)

if __name__ == "__main__":
    scraper = ScraperSP()
    scraper.run()