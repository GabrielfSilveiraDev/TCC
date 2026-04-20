from base_scraper import SeleniumScraper
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import re
import os

class ScraperMG(SeleniumScraper):
    def __init__(self):
        super().__init__("TCE-MG", "Dados_MG", headless=False)
        self.url_base = "https://capmg.tce.mg.gov.br/view/xhtml/pesquisaRemuneracao.xhtml"
        self.ano_limite = 2020
        self.meses_mapa = {
            "Janeiro": "01", "Fevereiro": "02", "Março": "03", "Abril": "04",
            "Maio": "05", "Junho": "06", "Julho": "07", "Agosto": "08",
            "Setembro": "09", "Outubro": "10", "Novembro": "11", "Dezembro": "12"
        }

    def _aguardar_ajax_primefaces(self, tempo_limite=20):
        try:
            WebDriverWait(self.driver, tempo_limite).until(
                lambda d: d.execute_script("return typeof jQuery !== 'undefined' && jQuery.active === 0")
            )
            time.sleep(0.5)
        except:
            pass

    def _selecionar_dropdown_primefaces(self, espera, nome_campo, xpath_select_oculto, texto_alvo):
        self.log(f"Selecionando {nome_campo}: {texto_alvo}...")
        try:
            select_oculto = espera.until(EC.presence_of_element_located((By.XPATH, xpath_select_oculto)))
            container_dropdown = select_oculto.find_element(By.XPATH, "../..")
            gatilho = container_dropdown.find_element(By.CSS_SELECTOR, ".ui-selectonemenu-trigger")
            self.driver.execute_script("arguments[0].click();", gatilho)
            time.sleep(1)
            try:
                xpath_opcao = f"//div[contains(@class, 'ui-selectonemenu-panel') and contains(@style, 'display: block')]//li[text()='{texto_alvo}']"
                opcao = espera.until(EC.element_to_be_clickable((By.XPATH, xpath_opcao)))
            except:
                xpath_opcao = f"//div[contains(@class, 'ui-selectonemenu-panel') and contains(@style, 'display: block')]//li[contains(text(), '{texto_alvo}')]"
                opcao = espera.until(EC.element_to_be_clickable((By.XPATH, xpath_opcao)))
            self.driver.execute_script("arguments[0].click();", opcao)
            self.log("OK.")
            self._aguardar_ajax_primefaces()
            return True
        except Exception as e:
            self.log(f"Falha ({type(e).__name__}).")
            self.driver.execute_script("window.scrollTo(0, 0);")
            self.driver.refresh()
            self._aguardar_ajax_primefaces()
            return False

    def scrape(self):
        espera = WebDriverWait(self.driver, 15)
        espera_longa = WebDriverWait(self.driver, 300)
        self.log("Acessando portal...")
        self.driver.get(self.url_base)
        self._aguardar_ajax_primefaces()
        self.log("Entrando como Cidadao...")
        try:
            xpath_cidadao = "//button[.//span[text()='CLIQUE AQUI SE VOCÊ É CIDADÃO']]"
            btn_cidadao = espera.until(EC.element_to_be_clickable((By.XPATH, xpath_cidadao)))
            self.driver.execute_script("arguments[0].click();", btn_cidadao)
            self.log("ATENCAO: Por favor, resolva o reCAPTCHA no navegador manualmente. Aguardando...")
            xpath_select_ano = "//select[option[contains(text(), '2025')]]"
            espera_longa.until(EC.presence_of_element_located((By.XPATH, xpath_select_ano)))
            self.log("Acesso ao sistema confirmado. Retomando automacao...")
            time.sleep(1)
        except Exception:
            self.log("Falha ao acessar ou tempo limite do CAPTCHA excedido.")
            return

        progress = self._load_progress()
        processed_periods = progress.get('processed_periods', [])

        self.log("FASE 1: Enfileirando Exportacoes...")

        meses_enfileirados = 0
        for ano in range(2025, self.ano_limite - 1, -1):
            
            meses_do_ano = list(self.meses_mapa.keys())
            if ano == 2025:
                meses_do_ano = ["Setembro", "Agosto", "Julho", "Junho", "Maio", "Abril", "Março", "Fevereiro", "Janeiro"]
            
            for mes in meses_do_ano:
                periodo_str = f"{mes}-{ano}"
                mes_num = self.meses_mapa.get(mes, "00")
                nome_padrao = f"tce_mg_{mes_num}_{ano}.json"
                caminho_padrao = os.path.join(self.output_folder, nome_padrao)
                
                if periodo_str in processed_periods or os.path.exists(caminho_padrao):
                    self.log(f"Período {periodo_str} já processado ou arquivo existe. Pulando fila.")
                    if periodo_str not in processed_periods:
                        processed_periods.append(periodo_str)
                        self._save_progress({'processed_periods': processed_periods})
                    continue
                
                self.log(f"Preparando: {mes}/{ano}")
                if not self._selecionar_dropdown_primefaces(espera, "Ano", "//select[option[contains(text(), '2025')]]", str(ano)): continue
                if not self._selecionar_dropdown_primefaces(espera, "Mes", "//select[option[contains(text(), 'Janeiro')]]", mes): continue
                if not self._selecionar_dropdown_primefaces(espera, "Esfera", "//select[contains(@id, 'idEsfera_input')]", "Estadual"): continue
                time.sleep(1.5)
                if not self._selecionar_dropdown_primefaces(espera, "Orgao", "//select[contains(@id, 'comboOrgao_input')]", "Tribunal de Contas do Estado de Minas Gerais"): continue
                time.sleep(1)
                
                try:
                    self.log("Clicando em Pesquisar...")
                    btn_pesquisar = self.driver.find_element(By.XPATH, "//button[.//span[text()='Pesquisar']]")
                    self.driver.execute_script("arguments[0].click();", btn_pesquisar)
                    self._aguardar_ajax_primefaces()
                    time.sleep(1)
                    self.log("OK.")
                except Exception:
                    self.log("Falha ao pesquisar.")
                    continue
                
                try:
                    sucesso_exportacao = False
                    for _ in range(3):
                        try:
                            espera_exportar = WebDriverWait(self.driver, 10)
                            btn_exportar = espera_exportar.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btnExportar a.linksArquivosJson")))
                            self.driver.execute_script("arguments[0].click();", btn_exportar)
                            sucesso_exportacao = True
                            break
                        except Exception:
                            time.sleep(1)
                            
                    if sucesso_exportacao:
                        self.log("Exportacao JSON solicitada.")
                        self._aguardar_ajax_primefaces()
                        time.sleep(1)
                    else:
                        self.log("Falha ao clicar no botao de exportar (DOM instavel).")
                except TimeoutException:
                    self.log("Botao de exportar JSON nao apareceu apos 10s (Tabela vazia?).")
                except Exception as e:
                    self.log(f"Erro inesperado ao exportar: {type(e).__name__}")
                
                meses_enfileirados += 1
        
        self.log(f"Total de meses enfileirados: {meses_enfileirados}. Aguardando 10 segundos para o servidor processar as filas finais...")
        time.sleep(10)
        self.log("FASE 2: Baixando e Renomeando Arquivos Processados...")
        try:
            xpath_gerenciar = "//button[contains(@class, 'ui-button') and .//span[contains(text(), 'Gerenciar downloads')]]"
            btn_gerenciar = espera.until(EC.presence_of_element_located((By.XPATH, xpath_gerenciar)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_gerenciar)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn_gerenciar)
            self._aguardar_ajax_primefaces()
            css_base_modal = "div[id$='dialogArquivosExportados']"
            espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, css_base_modal)))
            time.sleep(2)
        except Exception as e:
            self.log(f"Nao foi possivel abrir o modal de downloads. Erro: {type(e).__name__} - {str(e)}")
            return

        pagina = 1
        while True:
            self.log(f"Lendo pagina {pagina} de downloads no modal...")
            try:
                css_linhas = f"{css_base_modal} tbody[id$='dataTableResultados_data'] tr"
                linhas = self.driver.find_elements(By.CSS_SELECTOR, css_linhas)
                if not linhas or "Nenhum registro" in linhas[0].text:
                    self.log("Nenhuma linha encontrada na tabela do modal.")
                    break
                ref_primeira_linha = linhas[0]
                for i in range(len(linhas)):
                    linhas_atuais = self.driver.find_elements(By.CSS_SELECTOR, css_linhas)
                    if i >= len(linhas_atuais): break
                    linha = linhas_atuais[i]
                    texto_linha = linha.text.upper()
                    if "FINALIZADO" in texto_linha and "JSON" in texto_linha:
                        try:
                            ano_ext = re.search(r'EXERCÍCIO:\s*(\d{4})', texto_linha).group(1)
                            mes_ext = re.search(r'MÊS:\s*([A-ZÇ]+)', texto_linha).group(1)
                            mes_num = self.meses_mapa.get(mes_ext.capitalize(), "00")
                            nome_padrao = f"tce_mg_{mes_num}_{ano_ext}.json"
                            caminho_padrao = os.path.join(self.output_folder, nome_padrao)
                            if os.path.exists(caminho_padrao):
                                self.log(f"Arquivo {nome_padrao} já existe, pulando download.")
                                continue
                        except Exception:
                            nome_padrao = f"tce_mg_DESCONHECIDO_{int(time.time())}.json"
                            caminho_padrao = os.path.join(self.output_folder, nome_padrao)
                        
                        arquivos_antes = set(os.listdir(self.output_folder))
                        btn_baixar = linha.find_element(By.XPATH, ".//button[contains(@class, 'btnTabela') or .//span[contains(text(), 'Baixar')]]")
                        self.driver.execute_script("arguments[0].click();", btn_baixar)
                        tempo_limite_dl = 30
                        inicio_dl = time.time()
                        renomeado = False
                        while time.time() - inicio_dl < tempo_limite_dl:
                            arquivos_agora = set(os.listdir(self.output_folder))
                            novos = arquivos_agora - arquivos_antes
                            prontos = [f for f in novos if not f.endswith('.crdownload') and not f.endswith('.tmp')]
                            if prontos:
                                caminho_original = os.path.join(self.output_folder, prontos[0])
                                try:
                                    os.rename(caminho_original, caminho_padrao)
                                    self.log(f"Salvo localmente: {nome_padrao}")
                                    renomeado = True
                                    try:
                                        periodo_finalizado = f"{mes_ext.capitalize()}-{ano_ext}"
                                        if periodo_finalizado not in processed_periods:
                                            processed_periods.append(periodo_finalizado)
                                            self._save_progress({'processed_periods': processed_periods})
                                    except:
                                        pass
                                except Exception as e:
                                    self.log(f"Erro ao processar {prontos[0]}: {e}")
                                break
                            time.sleep(1)
                        if not renomeado:
                            self.log(f"Timeout ao baixar: {nome_padrao}")
                
                css_btn_prox = f"{css_base_modal} div[id$='dataTableResultados_paginator_bottom'] .ui-paginator-next"
                botoes_prox = self.driver.find_elements(By.CSS_SELECTOR, css_btn_prox)
                if not botoes_prox:
                    self.log("Fim da tabela (sem botao de paginacao no modal).")
                    break
                botao_prox = botoes_prox[0]
                if "ui-state-disabled" in botao_prox.get_attribute("class"):
                    self.log("Fim das paginas alcancado.")
                    break
                self.driver.execute_script("arguments[0].click();", botao_prox)
                self._aguardar_ajax_primefaces()
                try:
                    WebDriverWait(self.driver, 10).until(EC.staleness_of(ref_primeira_linha))
                except TimeoutException:
                    self.log("Fim da tabela detectado (A pagina nao recarregou apos o clique).")
                    break
                pagina += 1
            except Exception:
                self.log("Leitura finalizada.")
                break
        self.log("Processo de downloads concluido com sucesso.")

if __name__ == "__main__":
    scraper = ScraperMG()
    scraper.run()