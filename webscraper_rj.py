import time
import json
import requests
import os
import subprocess
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PASTA_SAIDA = "Dados_RJ"

if not os.path.exists(PASTA_SAIDA):
    os.makedirs(PASTA_SAIDA, exist_ok=True)

def configurar_navegador():
    """
    Summary: Configura o navegador Chrome em modo invisivel com otimizacoes de memoria para execucoes longas.
    Alteracoes: Nomes e configuracoes adaptadas para execucao local no Windows.
    """
    opcoes = Options()
    opcoes.add_argument("--headless=new")
    opcoes.add_argument("--disable-gpu")
    opcoes.add_argument("--window-size=1920,1080")
    opcoes.add_argument("--disable-software-rasterizer")
    opcoes.page_load_strategy = 'eager'
    
    navegador = webdriver.Chrome(options=opcoes)
    navegador.set_page_load_timeout(60)
    return navegador

def aguardar_carregamento_angular(navegador):
    """
    Summary: Aguarda o icone de carregamento do Angular desaparecer da tela para evitar cliques prematuros.
    """
    try:
        espera = WebDriverWait(navegador, 2)
        espera.until(EC.visibility_of_element_located((By.CLASS_NAME, "loading-container")))
        espera_longa = WebDriverWait(navegador, 30)
        espera_longa.until(EC.invisibility_of_element_located((By.CLASS_NAME, "loading-container")))
    except: 
        pass
    time.sleep(0.5)

def obter_referencias_api():
    """
    Summary: Consulta a API do portal para listar todos os meses e anos disponiveis para extracao.
    """
    cabecalhos = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    url = "https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/api/lov/referencia?busca=&page=1"

    try:
        resposta = requests.get(url, headers=cabecalhos, verify=True)
        resposta.raise_for_status()
        return [item['descricao'] for item in resposta.json()['dados']]
    except Exception as erro:
        print(f"Erro ao buscar API: {erro}")
        return []

def converter_valor_br(valor_texto):
    """
    Summary: Converte uma string de moeda no formato brasileiro para float padrao.
    """
    if not valor_texto: return 0.0
    return float(valor_texto.replace(".", "").replace(",", ".").strip())

def principal():
    """
    Summary: Funcao principal que orquestra a extracao do TCE-RJ e o envio para o Google Drive.
    Alteracoes: Variaveis e logs traduzidos para o portugues. O navegador e reiniciado a cada mes processado.
    """
    referencias = obter_referencias_api()
    ano_alvo = os.environ.get("ANO_ALVO")
    
    if ano_alvo:
        referencias = [ref for ref in referencias if ref.endswith(f"/{ano_alvo}")]
        
    print(f"Encontradas {len(referencias)} referencias para processar.")
    
    if not referencias:
        return

    for referencia in referencias:
        print(f"\nIniciando competencia: {referencia}")
        dados_mes = []
        
        navegador = configurar_navegador()
        espera = WebDriverWait(navegador, 20)

        try:
            navegador.get("https://tcerjtransparencia.admrh.inf.br/rhsysportaltransp/")
            espera.until(EC.presence_of_element_located((By.CLASS_NAME, "ui-select-container")))

            caixa_selecao = espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".ui-select-container .ui-select-toggle")))
            navegador.execute_script("arguments[0].click();", caixa_selecao)

            campo_busca = espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input.ui-select-search")))
            campo_busca.clear()
            campo_busca.send_keys(referencia)
            time.sleep(0.5) 
            campo_busca.send_keys(Keys.ENTER)

            aguardar_carregamento_angular(navegador)
            time.sleep(1) 
            
            linhas = navegador.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
            if not linhas or "nenhum registro" in navegador.page_source.lower():
                print(f"Sem dados encontrados para {referencia}.")
                navegador.quit()
                continue

            pagina = 1
            ultimo_nome = None 
            
            while True:
                print(f"  Lendo pagina {pagina} de {referencia}...")
                
                try:
                    nome_atual = navegador.find_element(By.CSS_SELECTOR, "table.table-selectable tbody tr td[data-title='Nome']").text.strip()
                    if ultimo_nome and nome_atual == ultimo_nome:
                        break
                    ultimo_nome = nome_atual
                except:
                    break

                linhas = navegador.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
                
                for i in range(len(linhas)):
                    linhas = navegador.find_elements(By.CSS_SELECTOR, "table.table-selectable tbody tr")
                    if i >= len(linhas): break
                    linha = linhas[i]

                    try:
                        nome = linha.find_element(By.CSS_SELECTOR, "td[data-title='Nome']").text.strip()
                        cargo = linha.find_element(By.CSS_SELECTOR, "td[data-title='Cargo']").text.strip()
                        tipo = linha.find_element(By.CSS_SELECTOR, "td[data-title='Vinculo']").text.strip()

                        navegador.execute_script("arguments[0].scrollIntoView({block: 'center'});", linha)
                        try: 
                            linha.click()
                        except: 
                            navegador.execute_script("arguments[0].click();", linha)
                        
                        espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".valores")))
                        blocos_valores = navegador.find_elements(By.CSS_SELECTOR, ".valores")

                        proventos = []
                        total_proventos = 0.0
                        total_descontos = 0.0
                        salario_liquido = 0.0

                        for bloco in blocos_valores:
                            try:
                                descricao = bloco.find_element(By.CSS_SELECTOR, ".column-string").text.strip()
                                valor_str = bloco.find_element(By.CSS_SELECTOR, ".column-number").text.strip()
                                valor = converter_valor_br(valor_str)

                                desc_min = descricao.lower()
                                if "deduções" in desc_min or "liquido" in desc_min or "líquido" in desc_min:
                                    salario_liquido = valor
                                elif "desconto" in desc_min or "retido" in desc_min:
                                    total_descontos += valor
                                    if valor > 0:
                                        proventos.append({"descricao": descricao, "valor": valor_str, "tipo": "D"})
                                else:
                                    total_proventos += valor
                                    if valor > 0:
                                        proventos.append({"descricao": descricao, "valor": valor_str, "tipo": "P"})
                            except: 
                                continue

                        dados_mes.append({
                            "referencia": referencia,
                            "nome": nome,
                            "cargo": cargo,
                            "tipo": tipo,
                            "salario_liquido": f"{salario_liquido:,.2f}",
                            "total_proventos": f"{total_proventos:,.2f}",
                            "total_descontos": f"{total_descontos:,.2f}",
                            "detalhes": proventos
                        })

                        ActionChains(navegador).send_keys(Keys.ESCAPE).perform()
                        espera.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, ".valores")))

                    except Exception:
                        try:
                            ActionChains(navegador).send_keys(Keys.ESCAPE).perform()
                        except:
                            pass
                        continue

                try:
                    navegador.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    botao_proximo = navegador.find_element(By.CSS_SELECTOR, "a[title='Próxima']")
                    li_pai = botao_proximo.find_element(By.XPATH, "./..")
                    
                    if "disabled" in li_pai.get_attribute("class"):
                        break

                    navegador.execute_script("arguments[0].click();", botao_proximo)
                    aguardar_carregamento_angular(navegador)
                    pagina += 1
                    
                except Exception:
                    break
            
            if dados_mes:
                nome_seguro = referencia.replace('/', '_')
                nome_arquivo = f"servidores_tce_rj_completo_{nome_seguro}.json"
                caminho_completo = os.path.join(PASTA_SAIDA, nome_arquivo)
                
                try:
                    with open(caminho_completo, "w", encoding="utf-8") as f:
                        json.dump(dados_mes, f, ensure_ascii=False, indent=4)
                    print(f"Salvo localmente: {nome_arquivo}")
                    
                    print(f"Enviando para o Google Drive...")
                    subprocess.run(["rclone", "move", caminho_completo, "meudrive:TCC_Scraping/Dados_RJ/"], check=True)
                    print(f"Upload concluido. Arquivo local apagado.")
                    
                except Exception as erro_salvamento:
                    print(f"Erro ao salvar/enviar {nome_arquivo}: {erro_salvamento}")

        except Exception as erro_geral:
            print(f"Erro critico em {referencia}: {erro_geral}")

        finally:
            navegador.quit()
            print("Navegador fechado. Memoria RAM liberada para o proximo ciclo.")

    print("Extracao finalizada.")

if __name__ == "__main__":
    principal()