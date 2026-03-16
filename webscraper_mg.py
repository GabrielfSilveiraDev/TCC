import os
import time
import re
import subprocess
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

URL_BASE = "https://capmg.tce.mg.gov.br/view/xhtml/pesquisaRemuneracao.xhtml"
PASTA_SAIDA = "Dados_MG"
ANO_LIMITE = 2020

MESES_MAPA = {
    "JANEIRO": "01", "FEVEREIRO": "02", "MARÇO": "03", "ABRIL": "04",
    "MAIO": "05", "JUNHO": "06", "JULHO": "07", "AGOSTO": "08",
    "SETEMBRO": "09", "OUTUBRO": "10", "NOVEMBRO": "11", "DEZEMBRO": "12"
}

if not os.path.exists(PASTA_SAIDA):
    os.makedirs(PASTA_SAIDA)

def configurar_navegador():
    """
    Summary: Configura o navegador Chrome com configuracoes de download automatico.
    Alteracoes: Remocao de emojis e adicao de otimizacoes de memoria (GPU, rasterizer).
    """
    opcoes = Options()
    # opcoes.add_argument("--headless=new") # Descomente para rodar invisivel apos passar o CAPTCHA
    opcoes.add_argument("--start-maximized")
    opcoes.add_argument("--no-sandbox")
    opcoes.add_argument("--disable-dev-shm-usage")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--disable-software-rasterizer")
    
    preferencias = {
        "download.default_directory": os.path.abspath(PASTA_SAIDA),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.automatic_downloads": 1 
    }
    opcoes.add_experimental_option("prefs", preferencias)
    return webdriver.Chrome(options=opcoes)

def aguardar_ajax_primefaces(navegador, tempo_limite=20):
    """
    Summary: Aguarda requisicoes AJAX do PrimeFaces (jQuery) finalizarem para evitar quebra do DOM.
    """
    try:
        WebDriverWait(navegador, tempo_limite).until(
            lambda d: d.execute_script("return typeof jQuery !== 'undefined' && jQuery.active === 0")
        )
        time.sleep(0.5) 
    except:
        pass

def selecionar_dropdown_primefaces(navegador, espera, nome_campo, xpath_select_oculto, texto_alvo):
    """
    Summary: Seleciona uma opcao em um dropdown do PrimeFaces usando seu select oculto.
    """
    print(f"Selecionando {nome_campo}: {texto_alvo}...", end=" ")
    try:
        select_oculto = espera.until(EC.presence_of_element_located((By.XPATH, xpath_select_oculto)))
        container_dropdown = select_oculto.find_element(By.XPATH, "../..")
        
        gatilho = container_dropdown.find_element(By.CSS_SELECTOR, ".ui-selectonemenu-trigger")
        navegador.execute_script("arguments[0].click();", gatilho)
        time.sleep(1) 
        
        try:
            xpath_opcao = f"//div[contains(@class, 'ui-selectonemenu-panel') and contains(@style, 'display: block')]//li[text()='{texto_alvo}']"
            opcao = espera.until(EC.element_to_be_clickable((By.XPATH, xpath_opcao)))
        except:
            xpath_opcao = f"//div[contains(@class, 'ui-selectonemenu-panel') and contains(@style, 'display: block')]//li[contains(text(), '{texto_alvo}')]"
            opcao = espera.until(EC.element_to_be_clickable((By.XPATH, xpath_opcao)))

        navegador.execute_script("arguments[0].click();", opcao)
        
        print("OK.")
        aguardar_ajax_primefaces(navegador)
        return True
    except Exception as e:
        print(f"Falha ({type(e).__name__}).")
        webdriver.ActionChains(navegador).send_keys(webdriver.Keys.ESCAPE).perform()
        return False

def principal():
    """
    Summary: Fluxo principal de execucao do web scraper para o portal TCE-MG.
    Alteracoes: Textos em portugues e integracao com Rclone para limpeza automatica do disco.
    """
    print(f"Iniciando Scraper TCE-MG em {datetime.now().strftime('%H:%M:%S')}")
    navegador = configurar_navegador()
    espera = WebDriverWait(navegador, 15)
    espera_longa = WebDriverWait(navegador, 300) 

    try:
        print("Acessando portal...")
        navegador.get(URL_BASE)
        aguardar_ajax_primefaces(navegador)

        print("Entrando como Cidadao...")
        try:
            xpath_cidadao = "//button[.//span[text()='CLIQUE AQUI SE VOCÊ É CIDADÃO']]"
            btn_cidadao = espera.until(EC.element_to_be_clickable((By.XPATH, xpath_cidadao)))
            navegador.execute_script("arguments[0].click();", btn_cidadao)
            
            print("\n" + "="*60)
            print("ATENCAO: Verificando reCAPTCHA...")
            print("Se o CAPTCHA aparecer na tela, resolva manualmente e clique em ENTRAR.")
            print("O script aguardara ate 5 minutos por voce...")
            print("="*60 + "\n")

            xpath_select_ano = "//select[option[contains(text(), '2025')]]"
            espera_longa.until(EC.presence_of_element_located((By.XPATH, xpath_select_ano)))
            print("Acesso ao sistema confirmado. Retomando automacao...\n")
            time.sleep(1) 
            
        except Exception:
            print("Falha ao acessar ou tempo limite do CAPTCHA excedido.")
            return

        print("\nFASE 1: Enfileirando Exportacoes...")
        
        for ano in range(2025, ANO_LIMITE - 1, -1):
            if ano == 2025:
                meses = ["Setembro", "Agosto", "Julho", "Junho", "Maio", "Abril", "Março", "Fevereiro", "Janeiro"]
            else:
                meses = ["Dezembro", "Novembro", "Outubro", "Setembro", "Agosto", "Julho", "Junho", "Maio", "Abril", "Março", "Fevereiro", "Janeiro"]

            for mes in meses:
                print(f"\nPreparando: {mes}/{ano}")
                
                selecionar_dropdown_primefaces(navegador, espera, "Ano", "//select[option[contains(text(), '2025')]]", str(ano))
                selecionar_dropdown_primefaces(navegador, espera, "Mes", "//select[option[contains(text(), 'Janeiro')]]", mes)
                selecionar_dropdown_primefaces(navegador, espera, "Esfera", "//select[contains(@id, 'idEsfera_input')]", "Estadual")
                time.sleep(1.5) 
                selecionar_dropdown_primefaces(navegador, espera, "Orgao", "//select[contains(@id, 'comboOrgao_input')]", "Tribunal de Contas do Estado de Minas Gerais")
                time.sleep(1)
                
                try:
                    print("Clicando em Pesquisar...", end=" ")
                    btn_pesquisar = navegador.find_element(By.XPATH, "//button[.//span[text()='Pesquisar']]")
                    navegador.execute_script("arguments[0].click();", btn_pesquisar)
                    aguardar_ajax_primefaces(navegador)
                    time.sleep(1) 
                    print("OK.")
                except Exception:
                    print("Falha ao pesquisar.")
                    continue 

                try:
                    sucesso_exportacao = False
                    for _ in range(3):
                        try:
                            espera_exportar = WebDriverWait(navegador, 10)
                            btn_exportar = espera_exportar.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".btnExportar a.linksArquivosJson")))
                            navegador.execute_script("arguments[0].click();", btn_exportar)
                            sucesso_exportacao = True
                            break 
                        except Exception:
                            time.sleep(1)
                
                    if sucesso_exportacao:
                        print("Exportacao JSON solicitada.")
                        aguardar_ajax_primefaces(navegador)
                        time.sleep(1)
                    else:
                        print("Falha ao clicar no botao de exportar (DOM instavel).")
                        
                except TimeoutException:
                    print("Botao de exportar JSON nao apareceu apos 10s (Tabela vazia?).")
                except Exception as e:
                    print(f"Erro inesperado ao exportar: {type(e).__name__}")

        print("\nAguardando 10 segundos para o servidor processar as filas finais...")
        time.sleep(10)

        print("\nFASE 2: Baixando e Renomeando Arquivos Processados...")

        try:
            btn_gerenciar = espera.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Gerenciar downloads']]")))
            navegador.execute_script("arguments[0].click();", btn_gerenciar)
            aguardar_ajax_primefaces(navegador)
            
            css_base_modal = "div[id$='dialogArquivosExportados']"
            espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, css_base_modal)))
            time.sleep(1) 
        except Exception:
            print("Nao foi possivel abrir o modal de downloads.")
            return

        pagina = 1
        while True:
            print(f"Lendo pagina {pagina} de downloads no modal...")
            
            try:
                css_linhas = f"{css_base_modal} tbody[id$='dataTableResultados_data'] tr"
                linhas = navegador.find_elements(By.CSS_SELECTOR, css_linhas)
                
                if not linhas or "Nenhum registro" in linhas[0].text:
                    print("Nenhuma linha encontrada na tabela do modal.")
                    break

                ref_primeira_linha = linhas[0]
                
                for i in range(len(linhas)):
                    linhas_atuais = navegador.find_elements(By.CSS_SELECTOR, css_linhas)
                    if i >= len(linhas_atuais): break
                    linha = linhas_atuais[i]
                    
                    texto_linha = linha.text.upper()
                    
                    if "FINALIZADO" in texto_linha and "JSON" in texto_linha:
                        
                        try:
                            ano_ext = re.search(r'EXERCÍCIO:\s*(\d{4})', texto_linha).group(1)
                            mes_ext = re.search(r'MÊS:\s*([A-ZÇ]+)', texto_linha).group(1)
                            mes_num = MESES_MAPA.get(mes_ext, "00")
                            nome_padrao = f"servidores_tce_mg_completo_{mes_num}_{ano_ext}.json"
                            caminho_padrao = os.path.join(PASTA_SAIDA, nome_padrao)
                            
                            if os.path.exists(caminho_padrao):
                                os.remove(caminho_padrao)
                        except Exception:
                            nome_padrao = f"servidores_tce_mg_completo_DESCONHECIDO_{int(time.time())}.json"
                            caminho_padrao = os.path.join(PASTA_SAIDA, nome_padrao)
                        
                        arquivos_antes = set(os.listdir(PASTA_SAIDA))
                        
                        btn_baixar = linha.find_element(By.CSS_SELECTOR, "button.btnTabela")
                        navegador.execute_script("arguments[0].click();", btn_baixar)
                        
                        tempo_limite_dl = 30
                        inicio_dl = time.time()
                        renomeado = False
                        
                        while time.time() - inicio_dl < tempo_limite_dl:
                            arquivos_agora = set(os.listdir(PASTA_SAIDA))
                            novos = arquivos_agora - arquivos_antes
                            
                            prontos = [f for f in novos if not f.endswith('.crdownload') and not f.endswith('.tmp')]
                            
                            if prontos:
                                caminho_original = os.path.join(PASTA_SAIDA, prontos[0])
                                try:
                                    os.rename(caminho_original, caminho_padrao)
                                    print(f"Salvo localmente: {nome_padrao}")
                                    renomeado = True
                                    
                                    print("Enviando arquivo para o Google Drive...")
                                    subprocess.run(["rclone", "move", caminho_padrao, f"meudrive:TCC_Scraping/{PASTA_SAIDA}/"], check=True)
                                    print("Upload concluido e arquivo local apagado.")
                                    
                                except Exception as e:
                                    print(f"Erro ao processar {prontos[0]}: {e}")
                                break
                            time.sleep(1)
                        
                        if not renomeado:
                            print(f"Timeout ao baixar: {nome_padrao}")
                
                css_btn_prox = f"{css_base_modal} div[id$='dataTableResultados_paginator_bottom'] .ui-paginator-next"
                botoes_prox = navegador.find_elements(By.CSS_SELECTOR, css_btn_prox)
                
                if not botoes_prox:
                    print("Fim da tabela (sem botao de paginacao no modal).")
                    break
                    
                botao_prox = botoes_prox[0]
                
                if "ui-state-disabled" in botao_prox.get_attribute("class"):
                    print("Fim das paginas alcancado.")
                    break 
                
                navegador.execute_script("arguments[0].click();", botao_prox)
                aguardar_ajax_primefaces(navegador)
                
                try:
                    WebDriverWait(navegador, 10).until(EC.staleness_of(ref_primeira_linha))
                except TimeoutException:
                    print("Fim da tabela detectado (A pagina nao recarregou apos o clique).")
                    break

                pagina += 1
                
            except Exception:
                print("Leitura finalizada.")
                break

        print(f"\nProcesso de downloads concluido com sucesso.")

    except Exception as e:
        print(f"\nErro Critico: {e}")
    finally:
        navegador.quit()
        print("Processo finalizado.")

if __name__ == "__main__":
    principal()