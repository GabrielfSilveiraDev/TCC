from base_scraper import SeleniumScraper
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import re

class ScraperPR(SeleniumScraper):
    def __init__(self):
        super().__init__("TCE-PR", "Dados_PR")
        self.url_pagina = "https://www.tce.pr.gov.br/transparencia-do-tce-pr/pessoal/remuneracao.htm"

    def _trigger_change(self, element):
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)

    def _get_valid_options(self, select_element, is_month=False):
        valid_options = []
        for opt in select_element.options:
            val = opt.get_attribute("value")
            text = opt.text.strip()
            if val and str(val).strip() != "" and "Selecione" not in text:
                if is_month:
                    try:
                        year = int(val.split(".")[0])
                        if year >= 2020:
                            valid_options.append((val, text))
                    except:
                        pass
                else:
                    valid_options.append((val, text))
        return valid_options

    def _extract_table_data(self, html_item):
        financial_data = {}
        rows = html_item.find_elements(By.CSS_SELECTOR, "tr.tp_table--tbody-tr")
        for row in rows:
            columns = row.find_elements(By.TAG_NAME, "td")
            if len(columns) == 2:
                key = columns[0].get_attribute("textContent").strip()
                value = columns[1].get_attribute("textContent").strip()
                if "R$" in value:
                    try:
                        clean_value = value.replace("R$", "").replace(".", "").replace(",", ".").replace(" ", "").strip()
                        financial_data[key] = float(clean_value)
                    except:
                        financial_data[key] = value
                else:
                    financial_data[key] = value
        return financial_data

    def _aguardar_naturezas(self, timeout=15):
        """Espera o dropdown de naturezas ser populado com opções válidas."""
        def naturezas_carregadas(driver):
            try:
                sel = Select(driver.find_element(By.NAME, "remuneracoes-natureza"))
                opts = [o for o in sel.options if o.get_attribute("value") and o.get_attribute("value").strip() and "Selecione" not in o.text]
                return len(opts) > 0
            except Exception:
                return False
        try:
            WebDriverWait(self.driver, timeout).until(naturezas_carregadas)
        except Exception:
            pass

    def _extrair_itens_pagina(self):
        """Extrai itens da página atual usando BeautifulSoup."""
        try:
            container = self.driver.find_element(By.ID, "remuneracoes-result-container")
            html = container.get_attribute("innerHTML")
        except Exception:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        return soup.select(".tp-dropdown-shadow--item")

    def _parse_item(self, item, mes_text, nat_text):
        """Parseia um item HTML em registro dict."""
        titulo_el = item.select_one(".tp-dropdown-shadow--item-title")
        nome_servidor = titulo_el.get_text(strip=True) if titulo_el else "Desconhecido"
        financeiro = {}
        for tr in item.select("tr.tp_table--tbody-tr"):
            tds = tr.find_all("td")
            if len(tds) == 2:
                key = tds[0].get_text(strip=True)
                value = tds[1].get_text(strip=True)
                if "R$" in value:
                    try:
                        clean = value.replace("R$", "").replace(".", "").replace(",", ".").replace(" ", "").strip()
                        financeiro[key] = float(clean)
                    except Exception:
                        financeiro[key] = value
                else:
                    financeiro[key] = value
        return {
            "periodo_folha": mes_text,
            "natureza_detalhada": nat_text,
            "nome": nome_servidor,
            "financeiro": financeiro
        }

    def _extract_pages(self, mes_text, nat_text):
        dados = []
        nomes_extraidos = set()
        pagina = 1
        while True:
            # Na primeira página, esperar curto; nas seguintes, esperar itens aparecerem
            if pagina == 1:
                time.sleep(1)
            else:
                try:
                    WebDriverWait(self.driver, 15).until(
                        lambda d: len(d.find_elements(By.CSS_SELECTOR, "#remuneracoes-result-container .tp-dropdown-shadow--item")) > 0
                    )
                    time.sleep(0.5)
                except Exception:
                    self.log(f"  Timeout aguardando itens da pagina {pagina}")
                    break
            itens = self._extrair_itens_pagina()
            if not itens:
                break
            novos = 0
            for item in itens:
                titulo_el = item.select_one(".tp-dropdown-shadow--item-title")
                nome = titulo_el.get_text(strip=True) if titulo_el else "Desconhecido"
                if nome in nomes_extraidos:
                    continue
                nomes_extraidos.add(nome)
                novos += 1
                dados.append(self._parse_item(item, mes_text, nat_text))
            if novos == 0:
                break
            # Paginação é irmã do container, não filha dele
            try:
                pag_div = self.driver.find_element(By.CSS_SELECTOR, "div.tp-pagination")
                visivel = pag_div.value_of_css_property("display") != "none"
                btn_next = pag_div.find_element(By.CSS_SELECTOR, "button.tp-pagination__btn-next")
                habilitado = btn_next.is_enabled()
                if not visivel or not habilitado:
                    break
            except Exception:
                break
            # Limpar container e clicar próxima página
            self.driver.execute_script("document.getElementById('remuneracoes-result-container').innerHTML = '';")
            self.driver.execute_script("arguments[0].click();", btn_next)
            pagina += 1
        return dados

    def scrape(self):
        wait = WebDriverWait(self.driver, 15)
        self.log("Acessando portal e aguardando JavaScript...")
        self.driver.get(self.url_pagina)
        time.sleep(5)

        progress = self._load_progress()
        processed_months = progress.get('processed_months', [])

        try:
            wait.until(lambda d: len(Select(d.find_element(By.NAME, "remuneracoes-mes-ano")).options) > 2)
        except:
            pass
        select_mes_element = Select(self.driver.find_element(By.NAME, "remuneracoes-mes-ano"))
        meses_disponiveis = self._get_valid_options(select_mes_element, is_month=True)
        meses_a_processar = [m for m in meses_disponiveis if m[1] not in processed_months]
        self.log(f"Meses carregados: {len(meses_disponiveis)}. A processar: {len(meses_a_processar)}")

        for mes_val, mes_text in meses_a_processar:
            self.log(f"Processando Mes: {mes_text}")
            dados_consolidados_mes = []

            # Selecionar mês e aguardar naturezas serem populadas pelo JS
            select_mes = self.driver.find_element(By.NAME, "remuneracoes-mes-ano")
            Select(select_mes).select_by_value(mes_val)
            self._trigger_change(select_mes)
            self._aguardar_naturezas(timeout=15)

            # Re-ler naturezas após seleção do mês
            select_nat_element = Select(self.driver.find_element(By.NAME, "remuneracoes-natureza"))
            naturezas_do_mes = self._get_valid_options(select_nat_element)
            
            if not naturezas_do_mes:
                self.log(f"Naturezas nao carregaram para {mes_text}. Recarregando pagina e tentando novamente...")
                self.driver.get(self.url_pagina)
                time.sleep(5)
                try:
                    wait.until(lambda d: len(Select(d.find_element(By.NAME, "remuneracoes-mes-ano")).options) > 2)
                except:
                    pass
                select_mes = self.driver.find_element(By.NAME, "remuneracoes-mes-ano")
                Select(select_mes).select_by_value(mes_val)
                self._trigger_change(select_mes)
                self._aguardar_naturezas(timeout=20)
                select_nat_element = Select(self.driver.find_element(By.NAME, "remuneracoes-natureza"))
                naturezas_do_mes = self._get_valid_options(select_nat_element)
            
            self.log(f"Naturezas para {mes_text}: {len(naturezas_do_mes)}")

            for nat_val, nat_text in naturezas_do_mes:
                self.log(f"Buscando: {nat_text}...")
                try:
                    self.driver.execute_script("document.getElementById('remuneracoes-result-container').innerHTML = '';")
                    select_nat = self.driver.find_element(By.NAME, "remuneracoes-natureza")
                    Select(select_nat).select_by_value(nat_val)
                    self._trigger_change(select_nat)
                    try:
                        WebDriverWait(self.driver, 20).until(
                            lambda d: len(d.find_elements(By.CSS_SELECTOR, "#remuneracoes-result-container .tp-dropdown-shadow--item")) > 0
                        )
                    except Exception:
                        self.log(f"Sem dados para {nat_text} (Timeout 20s)")
                        continue
                    self.log(f"Extraindo: {nat_text}")
                    novos_dados = self._extract_pages(mes_text, nat_text)
                    dados_consolidados_mes.extend(novos_dados)
                    self.log(f"  {len(novos_dados)} registros extraidos de {nat_text}")
                except Exception as e:
                    self.log(f"Erro ao extrair {nat_text}: {type(e).__name__}: {e}")
                    continue

            if dados_consolidados_mes:
                match = re.match(r'(\d{4})\.(\d{2})', mes_val)
                if match:
                    nome_arquivo = f"tce_pr_{match.group(2)}_{match.group(1)}.json"
                else:
                    nome_arquivo = f"tce_pr_{mes_val.replace('.', '_').replace(' ', '_')}.json"
                self.save_data_merge(dados_consolidados_mes, nome_arquivo, ['nome', 'periodo_folha', 'natureza_detalhada'])
            else:
                self.log("Sem dados para este mes inteiro.")

            processed_months.append(mes_text)
            self._save_progress({'processed_months': processed_months})

if __name__ == "__main__":
    scraper = ScraperPR()
    scraper.run()