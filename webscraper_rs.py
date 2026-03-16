import json
import os
import time
import re
import subprocess
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

URL_BASE = "https://portal.tce.rs.gov.br/aplicprod/f?p=10200:1:::NO:::"
PASTA_SAIDA = "Dados_RS"
ANO_LIMITE = 2020 

if not os.path.exists(PASTA_SAIDA):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    print(f"Pasta '{PASTA_SAIDA}' verificada/criada.")

def configurar_navegador():
    """
    Summary: Configura o navegador Chrome com carregamento rapido para prevenir travamentos em execucoes longas.
    Alteracoes: Nomes traduzidos para portugues e adaptado para execucao local no Windows.
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

def esperar_loading_apex(navegador):
    """
    Summary: Aguarda o icone de carregamento do sistema Apex desaparecer da tela.
    """
    try:
        espera = WebDriverWait(navegador, 2)
        espera.until(EC.visibility_of_element_located((By.CLASS_NAME, "u-Processing")))
        espera_longa = WebDriverWait(navegador, 30)
        espera_longa.until(EC.invisibility_of_element_located((By.CLASS_NAME, "u-Processing")))
    except: 
        pass
    time.sleep(0.3)

def extrair_ano_seguro(texto):
    """
    Summary: Utiliza expressoes regulares para encontrar um ano de 4 digitos no texto.
    """
    resultado = re.search(r'/.*?(\d{4})', texto)
    return int(resultado.group(1)) if resultado else None

def enviar_lote_para_drive(buffer_dados):
    """
    Summary: Salva os registros acumulados em um arquivo de lote unico e move para o Google Drive.
    Alteracoes: Textos traduzidos e emojis removidos. Mantem a exclusao automatica do arquivo local.
    """
    if not buffer_dados: return
    
    lote_dados = []
    for registros in buffer_dados.values():
        lote_dados.extend(registros)
        
    carimbo_tempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"servidores_tce_rs_lote_{carimbo_tempo}.json"
    caminho_arquivo = os.path.join(PASTA_SAIDA, nome_arquivo)
    
    try:
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            json.dump(lote_dados, f, ensure_ascii=False, indent=4)
        
        print(f"Lote salvo no disco: {nome_arquivo} ({len(lote_dados)} registros)")
        
        print("Enviando lote para o Google Drive...")
        subprocess.run(["rclone", "move", caminho_arquivo, f"meudrive:TCC_Scraping/{PASTA_SAIDA}/"], check=True)
        print("Upload concluido e arquivo local apagado.")
        
    except subprocess.CalledProcessError as e:
        print(f"Erro ao enviar lote para o Drive: {e}")
    except Exception as e:
        print(f"Erro ao salvar lote: {e}")
        
    buffer_dados.clear()

def extrair_dados_da_tela(navegador, texto_mes_ano, nome_servidor):
    """
    Summary: Extrai os dados financeiros lendo os IDs especificos dos elementos na pagina do servidor.
    """
    dados = {"mes_ano": texto_mes_ano.strip(), "nome_servidor": nome_servidor}
    try:
        mapa_ids = {
            "P7_NOME": "nome", "P7_CARGO": "cargo", "P7_CLASSE": "classe", "P7_NIVEL": "nivel",
            "P7_FG": "funcao_gratificada", "P7_DT_INGRESSO_TCE": "data_ingresso",
            "P7_TEMPO_SERVICO_PUBLICO": "tempo_servico", "P7_VL_BRUTO_APOS_TETO": "remuneracao_bruta",
            "P7_VL_INDENIZATORIAS": "parcelas_indenizatorias", "P7_VL_ABONO_PERMANENCIA": "abono_permanencia",
            "P7_VL_TERCO_FERIAS": "terco_ferias", "P7_VL_GRATIFICACAO_NATALINA": "gratificacao_natalina",
            "P7_VL_DESCONTOS_LEGAIS": "descontos_legais", "P7_VL_LIQUIDO_APOS_DESCONTOS": "liquido"
        }
        for elemento in navegador.find_elements(By.CSS_SELECTOR, "span.display_only"):
            id_elemento = elemento.get_attribute("id")
            if id_elemento in mapa_ids: 
                dados[mapa_ids[id_elemento]] = elemento.text.strip()
    except: 
        pass
    return dados

def processar_servidor(navegador, url_servidor, nome_servidor):
    """
    Summary: Processa o historico de um unico servidor, capturando timeouts para evitar a quebra do script.
    """
    print(f"[{nome_servidor}] Lendo historico...")
    registros_servidor = []
    
    try:
        try:
            navegador.get(url_servidor)
        except TimeoutException:
            navegador.execute_script("window.stop();")
            
        esperar_loading_apex(navegador)
        
        espera = WebDriverWait(navegador, 10)
        caixa_selecao = Select(espera.until(EC.presence_of_element_located((By.ID, "P7_PERIODO"))))
        
        todas_opcoes = [opcao.text for opcao in caixa_selecao.options]
        datas_validas = []
        ano_alvo = os.environ.get("ANO_ALVO")
        
        for texto in todas_opcoes:
            ano = extrair_ano_seguro(texto)
            if ano:
                if ano_alvo:
                    if ano == int(ano_alvo):
                        datas_validas.append(texto)
                elif ano >= ANO_LIMITE:
                    datas_validas.append(texto)

        print(f"[{nome_servidor}] Extraindo {len(datas_validas)} meses...")

        for texto_data in datas_validas:
            try:
                caixa_selecao = Select(navegador.find_element(By.ID, "P7_PERIODO"))
                caixa_selecao.select_by_visible_text(texto_data)
                esperar_loading_apex(navegador)
                registros_servidor.append(extrair_dados_da_tela(navegador, texto_data, nome_servidor))
            except: 
                continue
    except Exception as e:
        print(f"Erro no perfil: {type(e).__name__}")
        
    return registros_servidor

def principal():
    """
    Summary: Funcao principal que orquestra a extracao do portal TCE-RS.
    Alteracoes: Textos em portugues e fluxo mantido para processamento em lotes.
    """
    print(f"Iniciando as {datetime.now().strftime('%H:%M:%S')}")
    navegador = configurar_navegador()
    urls_processadas = set()
    buffer_por_mes = {}
    servidores_processados_lote = 0
    TAMANHO_LOTE = 20
    
    try:
        print("Acessando lista de servidores...")
        try:
            navegador.get(URL_BASE)
        except TimeoutException:
            print("Timeout inicial. Forcando parada do carregamento...")
            navegador.execute_script("window.stop();")

        esperar_loading_apex(navegador)
        
        pagina = 1
        while True:
            links_servidores = []
            try:
                linhas = navegador.find_elements(By.CSS_SELECTOR, "table.a-IRR-table tbody tr")
                for linha in linhas:
                    colunas = linha.find_elements(By.TAG_NAME, "td")
                    if colunas:
                        link = colunas[0].find_element(By.TAG_NAME, "a")
                        links_servidores.append((link.text.strip(), link.get_attribute("href")))
            except: 
                pass

            print(f"\nPagina {pagina}: {len(links_servidores)} servidores encontrados.")

            for nome, url in links_servidores:
                if url in urls_processadas: 
                    continue
                
                navegador.execute_script("window.open('');")
                navegador.switch_to.window(navegador.window_handles[1])
                
                for registro in processar_servidor(navegador, url, nome):
                    mes_ano = registro.get("mes_ano")
                    if mes_ano:
                        if mes_ano not in buffer_por_mes: 
                            buffer_por_mes[mes_ano] = []
                        buffer_por_mes[mes_ano].append(registro)
                
                navegador.close()
                navegador.switch_to.window(navegador.window_handles[0])
                urls_processadas.add(url)
                servidores_processados_lote += 1
                
                if servidores_processados_lote >= TAMANHO_LOTE:
                    enviar_lote_para_drive(buffer_por_mes)
                    servidores_processados_lote = 0

            try:
                espera = WebDriverWait(navegador, 5)
                botao_proximo = espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.a-IRR-button--pagination[title='Próximo']")))
                if not botao_proximo.is_displayed(): 
                    break
                navegador.execute_script("arguments[0].click();", botao_proximo)
                esperar_loading_apex(navegador)
                pagina += 1
            except: 
                break
                
        enviar_lote_para_drive(buffer_por_mes)
    except Exception as e:
        print(f"Erro Fatal: {e}")
        enviar_lote_para_drive(buffer_por_mes)
    finally:
        navegador.quit()

if __name__ == "__main__":
    principal()