import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime
import os
import subprocess

URL_PRINCIPAL = 'https://servicos.tcesc.tc.br/contracheque_externo/index.php'
URL_DETALHES = 'https://servicos.tcesc.tc.br/contracheque_externo/folha-individual.php'
PASTA_SAIDA = 'Dados_SC'

ANO_INICIO = 2024
ANO_FIM = 2025

MAPA_CATEGORIAS = {
    "ATIVO": "1,3,6,8,9,11,13,16,17,19",
    "INATIVO": "2,4,10,15,18"
}

ATRASO_REQUISICAO_SEGUNDOS = 0.25 
TEMPO_ESPERA_BLOQUEIO_SEGUNDOS = 300 

def limpar_salario_para_float(salario_str):
    """
    Summary: Limpa a string de formato de moeda brasileira e converte para float.
    Alteracoes: Variavel e logica traduzidas para o portugues.
    """
    if not salario_str: return 0.0
    str_limpa = salario_str.replace('.', '').replace(',', '.')
    try:
        return float(str_limpa)
    except ValueError:
        return 0.0

def extrair_lista_servidores(conteudo_html):
    """
    Summary: Analisa as linhas da tabela principal para obter informacoes basicas dos servidores.
    """
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
                'Salario_Liquido_R$': limpar_salario_para_float(celulas[3].get_text(strip=True))
            })
    return lista_servidores

def buscar_detalhes_persistente(sessao, id_servidor, nome_servidor):
    """
    Summary: Busca detalhes do contracheque com logica persistente de repeticao (tratando erros 403/429).
    Formata 'proventos' e 'descontos' em dicionarios padronizados.
    Alteracoes: Logs limpos de emojis e traduzidos.
    """
    carga_dados = {'servidorId': id_servidor}
    
    while True: 
        try:
            resposta = sessao.post(URL_DETALHES, json=carga_dados)
            resposta.raise_for_status()
            
            detalhes_brutos = resposta.json()
            
            if 'proventos' in detalhes_brutos:
                detalhes_brutos['proventos'] = [
                    {"descricao": item[0], "valor": item[1]} for item in detalhes_brutos['proventos']
                ]
            
            if 'descontos' in detalhes_brutos:
                detalhes_brutos['descontos'] = [
                    {"descricao": item[0], "valor": item[1]} for item in detalhes_brutos['descontos']
                ]
            
            return detalhes_brutos

        except requests.exceptions.HTTPError as erro_http:
            codigo_status = erro_http.response.status_code
            if codigo_status in [403, 429, 500, 502, 503, 504]:
                print(f"    Bloqueio/Erro ({codigo_status}). Aguardando {TEMPO_ESPERA_BLOQUEIO_SEGUNDOS}s...")
                time.sleep(TEMPO_ESPERA_BLOQUEIO_SEGUNDOS)
                continue 
            else:
                print(f"  -> Erro irrecuperavel {codigo_status} para {nome_servidor}. Pulando.")
                return None

        except requests.exceptions.RequestException:
            print(f"  -> Erro de conexao. Aguardando 30s...")
            time.sleep(30)
            continue 

        except json.JSONDecodeError:
            print(f"  -> Resposta JSON invalida para {nome_servidor}. Pulando.")
            return None

def principal():
    """
    Summary: Fluxo principal de extracao do TCE-SC.
    Alteracoes: Integracao do envio via Rclone com caminho absoluto e fallback local para garantir execucao contínua.
    """
    if not os.path.exists(PASTA_SAIDA):
        os.makedirs(PASTA_SAIDA)
        print(f"Pasta '{PASTA_SAIDA}' pronta.")
    
    tempo_inicio = datetime.now()
    print(f"--- Iniciando Scraper SC as {tempo_inicio.strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    total_registros_salvos = 0
    
    cabecalhos = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': URL_PRINCIPAL 
    }

    sessao = requests.Session()
    sessao.headers.update(cabecalhos)
    
    for ano in range(ANO_INICIO, ANO_FIM + 1):
        
        ultimo_mes = 10 if ano == 2025 else 12
        
        for mes in range(1, ultimo_mes + 1):
            str_mes = str(mes).zfill(2)
            
            print(f"\n============================================")
            print(f" Processando: {str_mes}/{ano}")
            print(f"============================================")
            
            dados_consolidados_mes = []

            for situacao, ids_categorias in MAPA_CATEGORIAS.items():
                print(f"  > Buscando categoria: {situacao}...")
                
                carga_principal = {
                    'mes': str_mes,
                    'ano': str(ano),
                    'categorias_string': ids_categorias,
                    'nome': '' 
                }
                
                try:
                    resposta = sessao.post(URL_PRINCIPAL, data=carga_principal)
                    resposta.raise_for_status()
                    lista_servidores = extrair_lista_servidores(resposta.text)
                except Exception as e:
                    print(f"    Erro ao buscar lista: {e}")
                    continue

                if not lista_servidores:
                    print(f"    -> Nenhum servidor encontrado para {situacao}.")
                    continue

                for i, servidor in enumerate(lista_servidores):
                    print(f"    [{i+1}/{len(lista_servidores)}] {servidor['Nome']}...", end='\r')
                    
                    detalhes = buscar_detalhes_persistente(sessao, servidor['ID_Servidor_Completo'], servidor['Nome'])
                    
                    servidor['Detalhes_Remuneracao'] = detalhes
                    servidor['situacao'] = situacao 
                    
                    dados_consolidados_mes.append(servidor)
                    
                    time.sleep(ATRASO_REQUISICAO_SEGUNDOS)
                
                print("") 

            if dados_consolidados_mes:
                nome_arquivo = f"servidores_tce_sc_completo_{str_mes}_{ano}.json"
                caminho_absoluto = os.path.abspath(os.path.join(PASTA_SAIDA, nome_arquivo))
                
                try:
                    with open(caminho_absoluto, 'w', encoding='utf-8') as f:
                        json.dump(dados_consolidados_mes, f, indent=4, ensure_ascii=False)
                    
                    quantidade = len(dados_consolidados_mes)
                    total_registros_salvos += quantidade
                    print(f"Salvo localmente: {nome_arquivo} ({quantidade} registros)")
                    
                    comando_rclone = f'rclone move "{caminho_absoluto}" "meudrive:TCC_Scraping/{PASTA_SAIDA}/"'
                    subprocess.run(comando_rclone, shell=True, check=True)
                    print("Upload para o Drive concluido e arquivo local apagado.")
                    
                except subprocess.CalledProcessError as erro_processo:
                    print(f"Aviso: Rclone retornou erro. Arquivo garantido no HD local. {erro_processo}")
                except FileNotFoundError:
                    print("Aviso: Rclone nao encontrado no PATH. Arquivo garantido no HD local.")
                except Exception as e:
                    print(f"Erro ao salvar/enviar arquivo: {e}")
            else:
                print(f"Sem dados encontrados para {str_mes}/{ano}")

    tempo_fim = datetime.now()
    duracao = tempo_fim - tempo_inicio
    print(f"\nFinalizado em {duracao}.")
    print(f"Total de registros processados: {total_registros_salvos}")

if __name__ == "__main__":
    principal()