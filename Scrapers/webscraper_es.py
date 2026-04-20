from base_scraper import RequestsScraper
from bs4 import BeautifulSoup
import requests
import urllib3
import json


class ScraperES(RequestsScraper):
    def __init__(self):
        super().__init__("TCE-ES", "Dados_ES")
        self.url_lista = "https://acessoidentificado.tcees.tc.br/Servidores"
        self.url_base_detalhes = "https://acessoidentificado.tcees.tc.br"
        self.ano_limite = 2020
        self.situacoes = [("Ativo", "0"), ("Inativo", "1")]
        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://acessoidentificado.tcees.tc.br",
            "Referer": "https://acessoidentificado.tcees.tc.br/Servidores/"
        }
        self.session.headers.update(self.headers)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _limpar_texto(self, texto):
        if not texto: return ""
        return texto.strip().replace('\n', '').replace('\r', '').replace('\t', ' ')

    def _processar_historico_financeiro(self, creditos_brutos, descontos_brutos, info_base):
        mapa_historico = {}
        for item in creditos_brutos:
            ano = item.get('AnoReferencia')
            mes = item.get('MesReferencia')
            if not ano or int(ano) < self.ano_limite:
                continue
            chave = f"{ano}-{mes}"
            if chave not in mapa_historico:
                mapa_historico[chave] = info_base.copy()
                mapa_historico[chave].update({
                    "ano": int(ano),
                    "mes": int(mes),
                    "mes_ano": f"{int(mes):02d}/{ano}",
                    "financeiro": {"creditos": [], "descontos": []}
                })
            mapa_historico[chave]["financeiro"]["creditos"].append({
                "descricao": item.get('DescricaoEvento'),
                "valor": item.get('ValorEvento')
            })
        for item in descontos_brutos:
            ano = item.get('AnoReferencia')
            mes = item.get('MesReferencia')
            if not ano or int(ano) < self.ano_limite:
                continue
            chave = f"{ano}-{mes}"
            if chave not in mapa_historico:
                mapa_historico[chave] = info_base.copy()
                mapa_historico[chave].update({
                    "ano": int(ano),
                    "mes": int(mes),
                    "mes_ano": f"{int(mes):02d}/{ano}",
                    "financeiro": {"creditos": [], "descontos": []}
                })
            mapa_historico[chave]["financeiro"]["descontos"].append({
                "descricao": item.get('DescricaoEvento'),
                "valor": item.get('ValorEvento')
            })
        return list(mapa_historico.values())

    def _extrair_detalhes_servidor(self, url_relativa, info_base, buffer_por_mes):
        url_completa = f"{self.url_base_detalhes}{url_relativa}"
        try:
            resposta = self.session.get(url_completa, verify=False)
            resposta.raise_for_status()
            sopa = BeautifulSoup(resposta.text, 'html.parser')
            input_cred = sopa.find('input', id='conteudo-tableCreditos')
            input_desc = sopa.find('input', id='conteudo-tableDescontos')
            lista_creditos = json.loads(input_cred['value']) if input_cred and input_cred.get('value') else []
            lista_descontos = json.loads(input_desc['value']) if input_desc and input_desc.get('value') else []
            registros_mensais = self._processar_historico_financeiro(lista_creditos, lista_descontos, info_base)
            for registro in registros_mensais:
                mes_ano = registro['mes_ano']
                if mes_ano not in buffer_por_mes:
                    buffer_por_mes[mes_ano] = []
                buffer_por_mes[mes_ano].append(registro)
            return True
        except requests.exceptions.ConnectionError as e:
            self.log(f"  Erro de conexao para {info_base.get('nome', '?')}: {e}")
            return None
        except Exception:
            return False

    def scrape(self):
        progress = self._load_progress()
        processed_matriculas = set(progress.get('processed_matriculas', []))
        
        buffer_por_mes = {}
        servidores_processados_lote = 0
        servidores_processados_total = 0
        tamanho_lote = 50
        
        for nome_situacao, id_situacao in self.situacoes:
            self.log(f"Processando Situacao: {nome_situacao}")
            carga_dados = {
                "NomeFiltro": "",
                "MatriculaFiltro": "",
                "IdSetorFiltro": "",
                "IdCargoOuFuncaoFiltro": "",
                "IdcSituacaoEnum": id_situacao
            }
            try:
                resposta = self.session.post(self.url_lista, data=carga_dados, verify=False)
                resposta.raise_for_status()
            except Exception as e:
                self.log(f"Erro ao buscar lista para {nome_situacao}: {e}")
                continue

            sopa = BeautifulSoup(resposta.text, 'html.parser')
            linhas = sopa.select("tbody tr")
            if not linhas:
                linhas = sopa.find_all('tr')
            
            self.log(f"Encontrados {len(linhas)} servidores na lista.")
            
            for i, linha in enumerate(linhas):
                colunas = linha.find_all('td')
                if len(colunas) < 3:
                    continue
                try:
                    coluna_nome = colunas[0]
                    elemento_link = coluna_nome.find('a')
                    if not elemento_link:
                        continue
                    
                    url_detalhes = elemento_link['href']
                    matricula = url_detalhes.split('matricula=')[1].split('&')[0]

                    if matricula in processed_matriculas:
                        self.log(f"  [{i+1}/{len(linhas)}] Servidor {matricula} já processado. Pulando.")
                        continue

                    nome = self._limpar_texto(elemento_link.get_text())
                    lotacao = self._limpar_texto(colunas[1].get_text())
                    cargo = self._limpar_texto(colunas[2].get_text())
                    
                    info_base = {
                        "matricula": matricula,
                        "nome": nome,
                        "cargo": cargo,
                        "lotacao": lotacao,
                        "situacao": nome_situacao
                    }

                    self.log(f"  [{i+1}/{len(linhas)}] {nome}...",)
                    resultado = self._extrair_detalhes_servidor(url_detalhes, info_base, buffer_por_mes)
                    if resultado is None:
                        self.log(f"  Erro de rede. Servidor {matricula} NAO marcado como processado.")
                        continue
                    
                    processed_matriculas.add(matricula)
                    servidores_processados_lote += 1
                    servidores_processados_total += 1
                    
                    if servidores_processados_lote >= tamanho_lote:
                        self.log("Limite do lote atingido. Salvando e atualizando progresso...")
                        for mes_ano, registros in buffer_por_mes.items():
                            nome_seguro = mes_ano.replace('/', '_')
                            nome_arquivo = f"tce_es_{nome_seguro}.json"
                            self.save_data_merge(registros, nome_arquivo, ['matricula', 'mes_ano'])
                        buffer_por_mes.clear()
                        servidores_processados_lote = 0
                        self._save_progress({'processed_matriculas': list(processed_matriculas)})

                except Exception:
                    continue
            
            self.log(f"Concluido {nome_situacao}.")

        # Salva o buffer restante no final
        self.log("Salvando buffer final e atualizando progresso...")
        for mes_ano, registros in buffer_por_mes.items():
            nome_seguro = mes_ano.replace('/', '_')
            nome_arquivo = f"tce_es_{nome_seguro}.json"
            self.save_data_merge(registros, nome_arquivo, ['matricula', 'mes_ano'])
        
        buffer_por_mes.clear()
        self._save_progress({'processed_matriculas': list(processed_matriculas)})

if __name__ == "__main__":
    scraper = ScraperES()
    scraper.run()