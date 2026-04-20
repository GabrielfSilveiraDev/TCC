from base_scraper import RequestsScraper
from bs4 import BeautifulSoup
from datetime import datetime
import time
import requests
import json


class ScraperSC(RequestsScraper):
    def __init__(self):
        super().__init__("TCE-SC", "Dados_SC")
        self.url_principal = 'https://servicos.tcesc.tc.br/contracheque_externo/index.php'
        self.url_detalhes = 'https://servicos.tcesc.tc.br/contracheque_externo/folha-individual.php'
        self.ano_inicio = 2020
        self.ano_fim = datetime.now().year
        self.mapa_categorias = {
            "ATIVO": "1,3,6,8,9,11,13,16,17,19",
            "INATIVO": "2,4,10,15,18",
            "PENSIONISTA": "51,52",
            "ESTAGIARIO": "5,12"
        }
        self.atraso_requisicao_segundos = 0.25
        self.tempo_espera_bloqueio_segundos = 300
        self.session.headers.update({'Referer': self.url_principal})

    def _limpar_salario_para_float(self, salario_str):
        if not salario_str: return 0.0
        str_limpa = salario_str.replace('.', '').replace(',', '.')
        try:
            return float(str_limpa)
        except ValueError:
            return 0.0

    def _extrair_lista_servidores(self, conteudo_html):
        sopa = BeautifulSoup(conteudo_html, 'html.parser')
        corpo_tabela = sopa.find('tbody', id='tabelaFolhasBody')
        if not corpo_tabela:
            return []
        lista_servidores = []
        linhas = corpo_tabela.find_all('tr')
        for linha in linhas:
            celulas = linha.find_all('td')
            if len(celulas) == 4:
                lista_servidores.append({
                    'ID_Servidor_Completo': linha.get('data-id-servidor'),
                    'Nome': celulas[0].get_text(strip=True),
                    'Cargo_Principal': celulas[1].get_text(strip=True),
                    'Tipo_Folha': celulas[2].get_text(strip=True),
                    'Salario_Liquido_R$': self._limpar_salario_para_float(celulas[3].get_text(strip=True))
                })
        return lista_servidores

    def _buscar_detalhes_persistente(self, id_servidor, nome_servidor):
        carga_dados = {'servidorId': id_servidor}
        while True:
            try:
                resposta = self.session.post(self.url_detalhes, json=carga_dados)
                resposta.raise_for_status()
                detalhes_brutos = resposta.json()
                if 'proventos' in detalhes_brutos:
                    detalhes_brutos['proventos'] = [{"descricao": item[0], "valor": item[1]} for item in detalhes_brutos['proventos']]
                if 'descontos' in detalhes_brutos:
                    detalhes_brutos['descontos'] = [{"descricao": item[0], "valor": item[1]} for item in detalhes_brutos['descontos']]
                return detalhes_brutos
            except requests.exceptions.HTTPError as erro_http:
                codigo_status = erro_http.response.status_code
                if codigo_status in [403, 429, 500, 502, 503, 504]:
                    self.log(f"Bloqueio/Erro ({codigo_status}). Aguardando {self.tempo_espera_bloqueio_segundos}s...")
                    time.sleep(self.tempo_espera_bloqueio_segundos)
                    continue
                else:
                    self.log(f"Erro irrecuperavel {codigo_status} para {nome_servidor}. Pulando.")
                    return None
            except requests.exceptions.RequestException:
                self.log("Erro de conexao. Aguardando 30s...")
                time.sleep(30)
                continue
            except json.JSONDecodeError:
                self.log(f"Resposta JSON invalida para {nome_servidor}. Pulando.")
                return None

    def scrape(self):
        progress = self._load_progress()
        last_processed_year = progress.get('year', self.ano_inicio)
        last_processed_month = progress.get('month', 0)

        total_registros_salvos = 0
        meses_processados = 0
        now = datetime.now()

        for ano in range(last_processed_year, self.ano_fim + 1):
            start_month = last_processed_month + 1 if ano == last_processed_year else 1
            ultimo_mes = now.month if ano == now.year else 12
            for mes in range(start_month, ultimo_mes + 1):
                str_mes = str(mes).zfill(2)
                self.log(f"Processando: {str_mes}/{ano}")
                dados_consolidados_mes = []
                for situacao, ids_categorias in self.mapa_categorias.items():
                    self.log(f"Buscando categoria: {situacao}...")
                    carga_principal = {'mes': str_mes, 'ano': str(ano), 'categorias_string': ids_categorias, 'nome': ''}
                    try:
                        resposta = self.session.post(self.url_principal, data=carga_principal)
                        resposta.raise_for_status()
                        lista_servidores = self._extrair_lista_servidores(resposta.text)
                    except Exception as e:
                        self.log(f"Erro ao buscar lista: {e}")
                        continue
                    if not lista_servidores:
                        self.log(f"Nenhum servidor encontrado para {situacao}.")
                        continue
                    for i, servidor in enumerate(lista_servidores):
                        self.log(f"    [{i+1}/{len(lista_servidores)}] {servidor['Nome']}...")
                        detalhes = self._buscar_detalhes_persistente(servidor['ID_Servidor_Completo'], servidor['Nome'])
                        servidor['Detalhes_Remuneracao'] = detalhes
                        servidor['situacao'] = situacao
                        dados_consolidados_mes.append(servidor)
                        time.sleep(self.atraso_requisicao_segundos)
                if dados_consolidados_mes:
                    nome_arquivo = f"tce_sc_{str_mes}_{ano}.json"
                    self.save_data(dados_consolidados_mes, nome_arquivo)
                    total_registros_salvos += len(dados_consolidados_mes)
                else:
                    self.log(f"Sem dados encontrados para {str_mes}/{ano}")
                
                self._save_progress({'year': ano, 'month': mes})
        self.log(f"Total de registros processados: {total_registros_salvos}")

if __name__ == "__main__":
    scraper = ScraperSC()
    scraper.run()