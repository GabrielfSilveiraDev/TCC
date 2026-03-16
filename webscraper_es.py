import requests
from bs4 import BeautifulSoup
import json
import os
import urllib3
import subprocess
from datetime import datetime

URL_LISTA = "https://acessoidentificado.tcees.tc.br/Servidores"
URL_BASE_DETALHES = "https://acessoidentificado.tcees.tc.br"
PASTA_SAIDA = "Dados_ES"
ANO_LIMITE = 2020 

SITUACOES = [
    ("Ativo", "0"),
    ("Inativo", "1")
]

CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://acessoidentificado.tcees.tc.br",
    "Referer": "https://acessoidentificado.tcees.tc.br/Servidores/"
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def limpar_texto(texto):
    """
    Summary: Remove quebras de linha e espacos extras de strings html.
    """
    if not texto: return ""
    return texto.strip().replace('\n', '').replace('\r', '').replace('\t', ' ')

def enviar_lotes_para_drive(buffer_dados):
    """
    Summary: Salva os registros fisicamente e tenta o envio via rclone com fallback local.
    Alteracoes: Uso de caminho absoluto e tratamento de excecoes focado na continuidade do script.
    """
    if not buffer_dados: return
    
    carimbo_tempo = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for mes_ano, registros in buffer_dados.items():
        if not registros: continue
        
        nome_seguro = mes_ano.replace('/', '_')
        nome_arquivo = f"servidores_tce_es_{nome_seguro}.json"
        
        caminho_absoluto = os.path.abspath(os.path.join(PASTA_SAIDA, nome_arquivo))
        
        try:
            with open(caminho_absoluto, 'w', encoding='utf-8') as f:
                json.dump(registros, f, ensure_ascii=False, indent=4)
                
            print(f"Lote salvo localmente: {nome_arquivo} ({len(registros)} registros)")
            
            comando_rclone = f'rclone move "{caminho_absoluto}" "meudrive:TCC_Scraping/{PASTA_SAIDA}/"'
            subprocess.run(comando_rclone, shell=True, check=True)
            print("Upload para o Drive concluido.")
            
        except subprocess.CalledProcessError as erro_processo:
            print(f"Aviso: Rclone retornou erro. Arquivo garantido no HD local. {erro_processo}")
        except FileNotFoundError:
            print("Aviso: Rclone nao encontrado no PATH do Windows. Arquivo garantido no HD local.")
        except Exception as e:
            print(f"Erro inesperado na manipulacao do arquivo {nome_arquivo}: {e}")
            
    buffer_dados.clear()


def processar_historico_financeiro(creditos_brutos, descontos_brutos, info_base):
    """
    Summary: Agrupa as listas brutas de creditos e descontos em registros mensais estruturados.
    """
    mapa_historico = {}
    
    for item in creditos_brutos:
        ano = item.get('AnoReferencia')
        mes = item.get('MesReferencia')
        
        if not ano or int(ano) < ANO_LIMITE:
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
        
        if not ano or int(ano) < ANO_LIMITE:
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

def extrair_detalhes_servidor(sessao, url_relativa, info_base, buffer_por_mes):
    """
    Summary: Acessa a pagina de detalhes, extrai o JSON oculto e adiciona ao buffer mensal em memoria.
    """
    url_completa = f"{URL_BASE_DETALHES}{url_relativa}"
    
    try:
        resposta = sessao.get(url_completa, headers=CABECALHOS, verify=False)
        resposta.raise_for_status()
        
        sopa = BeautifulSoup(resposta.text, 'html.parser')
        
        input_cred = sopa.find('input', id='conteudo-tableCreditos')
        input_desc = sopa.find('input', id='conteudo-tableDescontos')
        
        lista_creditos = json.loads(input_cred['value']) if input_cred and input_cred.get('value') else []
        lista_descontos = json.loads(input_desc['value']) if input_desc and input_desc.get('value') else []
        
        registros_mensais = processar_historico_financeiro(lista_creditos, lista_descontos, info_base)
        
        for registro in registros_mensais:
            mes_ano = registro['mes_ano']
            if mes_ano not in buffer_por_mes:
                buffer_por_mes[mes_ano] = []
            buffer_por_mes[mes_ano].append(registro)
            
        return True
        
    except Exception:
        return False

def principal():
    """
    Summary: Funcao principal que orquestra a extracao do portal TCE-ES utilizando requests.
    Alteracoes: Adicionado o sistema de loteamento dinamico na memoria para integracao com Rclone.
    """
    if not os.path.exists(PASTA_SAIDA):
        os.makedirs(PASTA_SAIDA)
        
    print("Iniciando extrator TCE-ES...")
    sessao = requests.Session()
    buffer_por_mes = {}
    servidores_processados_lote = 0
    TAMANHO_LOTE = 50 

    for nome_situacao, id_situacao in SITUACOES:
        print(f"\nProcessando Situacao: {nome_situacao}")
        
        carga_dados = {
            "NomeFiltro": "",
            "MatriculaFiltro": "",
            "IdSetorFiltro": "",
            "IdCargoOuFuncaoFiltro": "",
            "IdcSituacaoEnum": id_situacao
        }
        
        try:
            resposta = sessao.post(URL_LISTA, data=carga_dados, headers=CABECALHOS, verify=False)
            resposta.raise_for_status()
        except Exception as e:
            print(f"Erro ao buscar lista para {nome_situacao}: {e}")
            continue

        sopa = BeautifulSoup(resposta.text, 'html.parser')
        linhas = sopa.select("tbody tr")
        if not linhas: 
            linhas = sopa.find_all('tr')
        
        print(f"Encontrados {len(linhas)} servidores na lista.")
        
        for i, linha in enumerate(linhas):
            colunas = linha.find_all('td')
            if len(colunas) < 3: 
                continue

            try:
                coluna_nome = colunas[0]
                elemento_link = coluna_nome.find('a')
                
                if not elemento_link: 
                    continue
                
                nome = limpar_texto(elemento_link.get_text())
                url_detalhes = elemento_link['href']
                matricula = url_detalhes.split('matricula=')[1].split('&')[0]
                
                lotacao = limpar_texto(colunas[1].get_text())
                cargo = limpar_texto(colunas[2].get_text())
                
                info_base = {
                    "matricula": matricula,
                    "nome": nome,
                    "cargo": cargo,
                    "lotacao": lotacao,
                    "situacao": nome_situacao
                }

                print(f"  [{i+1}/{len(linhas)}] {nome}...", end="\r")
                
                extrair_detalhes_servidor(sessao, url_detalhes, info_base, buffer_por_mes)
                
                servidores_processados_lote += 1
                
                if servidores_processados_lote >= TAMANHO_LOTE:
                    print("\nLimite do lote atingido.")
                    enviar_lotes_para_drive(buffer_por_mes)
                    servidores_processados_lote = 0
                
            except Exception:
                continue
        
        print(f"\nConcluido {nome_situacao}.")
        enviar_lotes_para_drive(buffer_por_mes)

    print("\nExtracao finalizada.")

if __name__ == "__main__":
    principal()