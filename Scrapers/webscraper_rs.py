from base_scraper import SeleniumScraper
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from urllib.parse import urlparse, parse_qs, unquote
import argparse
import collections
import glob
import json
import time
import re
import os

MESES_PT = {
    'janeiro': '01', 'fevereiro': '02', 'março': '03', 'marco': '03',
    'abril': '04', 'maio': '05', 'junho': '06',
    'julho': '07', 'agosto': '08', 'setembro': '09',
    'outubro': '10', 'novembro': '11', 'dezembro': '12'
}

SITUACOES = [("CA", "Ativos"), ("CI", "Inativos"), ("CE", "Exonerados")]


class ScraperRS(SeleniumScraper):
    def __init__(self):
        super().__init__("TCE-RS", "Dados_RS")
        self.url_base = "https://portal.tce.rs.gov.br/aplicprod/f?p=10200:1:::NO:::"
        self.ano_limite = 2020

    @staticmethod
    def matricula_da_url(url):
        """
        Extrai a matrícula do link do servidor. O Oracle APEX codifica os itens da página no
        parâmetro p: '10200:7:::NO:7:P7_MATRICULA,P10_...:17001560,Servidor,1'.
        """
        p = parse_qs(urlparse(unquote(url)).query).get("p", [""])[0].split(":")
        if len(p) < 8:
            return None
        itens = dict(zip(p[6].split(","), p[7].split(",")))
        return itens.get("P7_MATRICULA") or None

    def _esperar_loading_apex(self):
        try:
            espera = WebDriverWait(self.driver, 2)
            espera.until(EC.visibility_of_element_located((By.CLASS_NAME, "u-Processing")))
            espera_longa = WebDriverWait(self.driver, 30)
            espera_longa.until(EC.invisibility_of_element_located((By.CLASS_NAME, "u-Processing")))
        except:
            pass
        time.sleep(0.3)

    def _extrair_ano_seguro(self, texto):
        resultado = re.search(r'/.*?(\d{4})', texto)
        return int(resultado.group(1)) if resultado else None

    def _mes_ano_para_filename(self, mes_ano_texto):
        """Converte 'Março/2025' ou '03/2025' para 'tce_rs_03_2025.json'."""
        partes = mes_ano_texto.strip().split('/')
        if len(partes) != 2:
            return f"tce_rs_{mes_ano_texto.replace('/', '_')}.json"
        parte_mes, parte_ano = partes[0].strip(), partes[1].strip()
        if parte_mes.isdigit():
            mm = parte_mes.zfill(2)
        else:
            mm = MESES_PT.get(parte_mes.lower(), '00')
        return f"tce_rs_{mm}_{parte_ano}.json"

    def _extrair_dados_da_tela(self, texto_mes_ano, nome_servidor, matricula):
        dados = {"mes_ano": texto_mes_ano.strip(), "nome_servidor": nome_servidor, "matricula": matricula}
        try:
            mapa_ids = {
                "P7_NOME": "nome", "P7_CARGO": "cargo", "P7_CLASSE": "classe", "P7_NIVEL": "nivel",
                "P7_FG": "funcao_gratificada", "P7_DT_INGRESSO_TCE": "data_ingresso",
                "P7_TEMPO_SERVICO_PUBLICO": "tempo_servico", "P7_VL_BRUTO_APOS_TETO": "remuneracao_bruta",
                "P7_VL_INDENIZATORIAS": "parcelas_indenizatorias", "P7_VL_ABONO_PERMANENCIA": "abono_permanencia",
                "P7_VL_TERCO_FERIAS": "terco_ferias", "P7_VL_GRATIFICACAO_NATALINA": "gratificacao_natalina",
                "P7_VL_DESCONTOS_LEGAIS": "descontos_legais", "P7_VL_LIQUIDO_APOS_DESCONTOS": "liquido"
            }
            for elemento in self.driver.find_elements(By.CSS_SELECTOR, "span.display_only"):
                id_elemento = elemento.get_attribute("id")
                if id_elemento in mapa_ids:
                    dados[mapa_ids[id_elemento]] = elemento.text.strip()
        except:
            pass
        return dados

    def _processar_servidor(self, url_servidor, nome_servidor):
        self.log(f"[{nome_servidor}] Lendo historico...")
        matricula = self.matricula_da_url(url_servidor)
        registros_servidor = []
        try:
            try:
                self.driver.get(url_servidor)
            except TimeoutException:
                self.driver.execute_script("window.stop();")
            self._esperar_loading_apex()
            espera = WebDriverWait(self.driver, 10)
            caixa_selecao = Select(espera.until(EC.presence_of_element_located((By.ID, "P7_PERIODO"))))
            todas_opcoes = [opcao.text for opcao in caixa_selecao.options]
            datas_validas = []
            ano_alvo = os.environ.get("TARGET_YEAR")
            for texto in todas_opcoes:
                ano = self._extrair_ano_seguro(texto)
                if ano:
                    if ano_alvo:
                        if ano == int(ano_alvo):
                            datas_validas.append(texto)
                    elif ano >= self.ano_limite:
                        datas_validas.append(texto)
            self.log(f"[{nome_servidor}] Extraindo {len(datas_validas)} meses...")
            for texto_data in datas_validas:
                try:
                    caixa_selecao = Select(self.driver.find_element(By.ID, "P7_PERIODO"))
                    caixa_selecao.select_by_visible_text(texto_data)
                    self._esperar_loading_apex()
                    registros_servidor.append(self._extrair_dados_da_tela(texto_data, nome_servidor, matricula))
                except:
                    continue
        except Exception as e:
            self.log(f"Erro no perfil: {type(e).__name__}")
        return registros_servidor

    def _iterar_links_servidores(self):
        """Percorre as listas de ativos, inativos e exonerados, gerando (situação, nome, url) por servidor."""
        self.log("Acessando lista de servidores...")
        try:
            self.driver.get(self.url_base)
        except TimeoutException:
            self.log("Timeout inicial. Forcando parada do carregamento...")
            self.driver.execute_script("window.stop();")
        self._esperar_loading_apex()

        for cod_sit, nome_sit in SITUACOES:
            self.log(f"Processando situacao: {nome_sit}")
            try:
                Select(self.driver.find_element(By.ID, "P1_SITUACAO")).select_by_value(cod_sit)
                self._esperar_loading_apex()
            except Exception as e:
                self.log(f"Erro ao selecionar situacao {nome_sit}: {e}")
                continue

            pagina = 1
            while True:
                links_servidores = []
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "table.a-IRR-table tbody tr"))
                    )
                    for linha in self.driver.find_elements(By.CSS_SELECTOR, "table.a-IRR-table tbody tr"):
                        colunas = linha.find_elements(By.TAG_NAME, "td")
                        if colunas:
                            link = colunas[0].find_element(By.TAG_NAME, "a")
                            links_servidores.append((link.text.strip(), link.get_attribute("href")))
                except Exception as e:
                    self.log(f"Erro ao extrair links da pagina {pagina}: {e}")

                self.log(f"[{nome_sit}] Pagina {pagina}: {len(links_servidores)} servidores encontrados.")
                # Os links são lidos antes de abrir abas, pois abrir o detalhe invalida os elementos da lista.
                for nome, url in links_servidores:
                    yield nome_sit, nome, url

                try:
                    espera = WebDriverWait(self.driver, 5)
                    botao_proximo = espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.a-IRR-button--pagination[title='Próximo']")))
                    if not botao_proximo.is_displayed() or "is-disabled" in botao_proximo.get_attribute("class"):
                        break
                    self.driver.execute_script("arguments[0].click();", botao_proximo)
                    self._esperar_loading_apex()
                    pagina += 1
                except:
                    break

            self.log(f"Situacao {nome_sit} concluida.")

    def _salvar_buffer(self, buffer_por_mes):
        for mes_ano, lote_dados in buffer_por_mes.items():
            nome_arquivo = self._mes_ano_para_filename(mes_ano)
            self.save_data_merge(lote_dados, nome_arquivo, ['matricula', 'nome_servidor', 'mes_ano'])
        buffer_por_mes.clear()

    def scrape(self):
        progress = self._load_progress()
        urls_processadas = set(progress.get('processed_urls', []))

        buffer_por_mes = collections.defaultdict(list)
        servidores_processados_lote = 0
        tamanho_lote = 20

        for _, nome, url in self._iterar_links_servidores():
            if url in urls_processadas:
                self.log(f"URL {url} já processada. Pulando.")
                continue

            self.driver.execute_script("window.open('');")
            self.driver.switch_to.window(self.driver.window_handles[1])
            for registro in self._processar_servidor(url, nome):
                if registro.get("mes_ano"):
                    buffer_por_mes[registro["mes_ano"]].append(registro)
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[0])

            urls_processadas.add(url)
            servidores_processados_lote += 1
            if servidores_processados_lote >= tamanho_lote:
                self.log("Lote atingido. Salvando dados e progresso...")
                self._salvar_buffer(buffer_por_mes)
                servidores_processados_lote = 0
                self._save_progress({'processed_urls': list(urls_processadas)})

        if buffer_por_mes:
            self.log("Salvando dados restantes do buffer final...")
            self._salvar_buffer(buffer_por_mes)
            self._save_progress({'processed_urls': list(urls_processadas)})

    def _completar_mapa_pelo_progresso(self, mapa):
        """
        Servidores coletados no passado podem ter saído das listas atuais ou mudado de grafia. As URLs
        guardadas no progresso preservam a matrícula; para as que não constam do mapa, lê-se o nome
        na própria página de detalhe.
        """
        conhecidas = {m for matriculas in mapa.values() for m in matriculas}
        urls = self._load_progress().get("processed_urls", [])
        faltantes = [u for u in urls if self.matricula_da_url(u) not in conhecidas]
        self.log(f"URLs do progresso fora das listas atuais: {len(faltantes)}")
        for url in faltantes:
            try:
                self.driver.get(url)
                self._esperar_loading_apex()
                nome = WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.ID, "P7_NOME"))
                ).text.strip().upper()
                if nome:
                    mapa[nome].add(self.matricula_da_url(url))
                    self.log(f"  {nome} → {self.matricula_da_url(url)}")
            except Exception as erro:
                self.log(f"  Não foi possível ler o nome em {url}: {type(erro).__name__}")

    def enriquecer_matriculas(self):
        """
        Preenche a matrícula nos arquivos já coletados, que só guardavam o nome. O mapa nome → matrícula
        vem das listas do portal; nomes associados a mais de uma matrícula (homônimos) ficam sem
        preenchimento e são relatados, para não atribuir a remuneração à pessoa errada.
        """
        mapa = collections.defaultdict(set)
        for _, nome, url in self._iterar_links_servidores():
            matricula = self.matricula_da_url(url)
            if matricula:
                mapa[nome.strip().upper()].add(matricula)
        self._completar_mapa_pelo_progresso(mapa)
        homonimos = {n for n, m in mapa.items() if len(m) > 1}
        self.log(f"Mapa nome → matrícula: {len(mapa)} nomes, {len(homonimos)} homônimos.")

        sem_correspondencia, ambiguos, preenchidos = collections.Counter(), collections.Counter(), 0
        for caminho in sorted(glob.glob(os.path.join(self.output_folder, "tce_rs_*.json"))):
            with open(caminho, encoding="utf-8") as f:
                registros = json.load(f)
            alterado = False
            for registro in registros:
                if registro.get("matricula"):
                    continue
                nome = (registro.get("nome_servidor") or registro.get("nome") or "").strip().upper()
                matriculas = mapa.get(nome, set())
                if len(matriculas) == 1:
                    registro["matricula"] = next(iter(matriculas))
                    preenchidos += 1
                    alterado = True
                elif matriculas:
                    ambiguos[nome] += 1
                else:
                    sem_correspondencia[nome] += 1
            if alterado:
                with open(caminho, "w", encoding="utf-8") as f:
                    json.dump(registros, f, ensure_ascii=False, indent=4)

        self.save_data({
            "registros_preenchidos": preenchidos,
            "nomes_homonimos": {n: sorted(mapa[n]) for n in sorted(ambiguos)},
            "nomes_sem_correspondencia": dict(sem_correspondencia.most_common()),
        }, "relatorio_matriculas.json")
        self.log(f"Matrículas preenchidas: {preenchidos}. Registros ambíguos: {sum(ambiguos.values())}. "
                 f"Sem correspondência: {sum(sem_correspondencia.values())}.")

    def run(self, enriquecer=False):
        if enriquecer:
            try:
                self.enriquecer_matriculas()
            finally:
                self.shutdown()
        else:
            super().run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coletor do TCE-RS")
    parser.add_argument("--enriquecer-matriculas", action="store_true",
                        help="Preenche a matrícula nos arquivos já coletados, sem recoletar os meses.")
    args = parser.parse_args()
    ScraperRS().run(enriquecer=args.enriquecer_matriculas)
