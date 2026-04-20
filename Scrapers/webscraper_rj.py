from base_scraper import RequestsScraper
from bs4 import BeautifulSoup
import requests
import re
import time


class ScraperRJ(RequestsScraper):
    def __init__(self):
        super().__init__("TCE-RJ", "Dados_RJ")
        self.url_portal = "https://www.tcerj.tc.br/portlet-portaltransparencia/"
        self.ano_limite = 2020
        self.tamanho_lote = 50
        self.session_base = None  # Ex: "https://www.tcerj.tc.br/portlet-portaltransparencia/(S(abc123))/"
        self.sem_pag_html = None
        self._estabelecer_sessao()

    # ------------------------------------------------------------------
    # Sessão
    # ------------------------------------------------------------------

    def _extrair_session_base(self, url):
        """Extrai a parte base da URL de sessão (inclusive a barra final)."""
        m = re.match(r'(https?://[^/]*/portlet-portaltransparencia/\(S\([^)]+\)\)/)', url)
        return m.group(1) if m else None

    def _estabelecer_sessao(self):
        """
        Navega pela sequência obrigatória do portal:
          1. GET página inicial  → obtém redirect com token de sessão
          2. POST vazio          → simula clique em "Filtrar" e inicializa a listagem
          3. GET SemPaginacao    → carrega todos os servidores de uma vez
        """
        for tentativa in range(3):
            try:
                # ── Etapa 1: obter token de sessão via redirect ───────────────
                r = self.session.get(self.url_portal, timeout=30)
                r.raise_for_status()

                base = self._extrair_session_base(r.url)
                if not base:
                    # Token pode estar no corpo da página (meta-refresh, link, etc.)
                    m = re.search(r'/portlet-portaltransparencia/\(S\([^)]+\)\)/', r.text)
                    if m:
                        base = "https://www.tcerj.tc.br" + m.group(0)
                if not base:
                    self.log("Token de sessão não encontrado na resposta inicial.")
                    time.sleep(5)
                    continue

                self.session_base = base
                self.log(f"Token de sessão: {self.session_base}")

                # ── Etapa 2: POST "Filtrar" com filtros vazios ────────────────
                # Alguns portais ASP.NET exigem __RequestVerificationToken
                soup0 = BeautifulSoup(r.text, 'html.parser')
                csrf_input = soup0.find('input', {'name': '__RequestVerificationToken'})
                form_data = {
                    'NomeMatricula': '', 'CargoSelected': '', 'CarreiraSelected': '',
                    'OrgaoSelected': '', 'LocalSelected': '',
                    'DataAdmissaoSelected': '', 'DataDesligamentoSelected': '',
                    '-': 'Filtrar',
                }
                if csrf_input:
                    form_data['__RequestVerificationToken'] = csrf_input.get('value', '')

                r2 = self.session.post(self.session_base, data=form_data, timeout=60)
                # Não exigimos sucesso: se falhar continuamos e tentamos SemPaginacao diretamente

                # Atualizar session_base se o servidor devolveu nova URL de sessão
                novo_base = self._extrair_session_base(r2.url)
                if novo_base:
                    self.session_base = novo_base

                # ── Etapa 3: Localizar e carregar SemPaginacao ────────────────
                soup2 = BeautifulSoup(r2.text, 'html.parser')
                link_sem_pag = (
                    soup2.find('a', string=re.compile(r'Remover Pagina', re.I))
                    or soup2.find('a', href=re.compile(r'SemPaginacao', re.I))
                )
                if link_sem_pag:
                    href = link_sem_pag['href']
                    sem_pag_url = ("https://www.tcerj.tc.br" + href
                                   if href.startswith('/') else href)
                    # Atualizar session_base com token da href
                    novo_base = self._extrair_session_base(sem_pag_url)
                    if novo_base:
                        self.session_base = novo_base
                else:
                    sem_pag_url = self.session_base + "Home/SemPaginacao"

                self.log(f"Carregando lista completa: {sem_pag_url}")
                r3 = self.session.get(
                    sem_pag_url, timeout=300,
                    headers={'Referer': r2.url},
                )
                r3.raise_for_status()

                novo_base = self._extrair_session_base(r3.url)
                if novo_base:
                    self.session_base = novo_base

                self.sem_pag_html = r3.text
                self.log("Sessão estabelecida e lista completa carregada.")
                return

            except Exception as e:
                self.log(f"Tentativa {tentativa + 1} de sessão falhou: {e}")
                time.sleep(10)

        raise RuntimeError("Não foi possível estabelecer sessão com o portal TCE-RJ")

    # ------------------------------------------------------------------
    # Lista de servidores
    # ------------------------------------------------------------------

    def _obter_lista_servidores(self):
        """
        Extrai a lista de servidores do HTML da página SemPaginacao.
        Armazena `modal_path` — caminho após o token de sessão — para
        que possa ser reconstruído após eventual renovação de sessão.
        """
        self.log("Parseando lista de servidores...")
        servidores = []
        soup = BeautifulSoup(self.sem_pag_html, 'html.parser')
        linhas = soup.select('table tbody tr')

        if not linhas:
            self.log("Nenhuma linha encontrada na tabela de servidores.")
            return servidores

        for linha in linhas:
            link = (linha.find('a', class_='btnAbrirModal')
                    or linha.find('a', attrs={'data-matricula': True}))
            if not link:
                continue
            cols = linha.find_all('td')
            matricula = link.get('data-matricula', '').strip()
            # O link usa heaf="#" (typo no HTML do site) acionado por JS.
            # A URL do modal é sempre Home/Visualizar?matricula=<matricula>.
            modal_path = f"Home/Visualizar?matricula={matricula}" if matricula else None

            nome_completo = link.get_text(strip=True)
            nome = re.sub(r'^\d+/\d+\s*-\s*', '', nome_completo).strip()

            servidores.append({
                'matricula': matricula,
                'modal_path': modal_path,
                'nome': nome,
                'cargo': cols[1].get_text(strip=True) if len(cols) > 1 else '',
                'cargo_comissao': cols[2].get_text(strip=True) if len(cols) > 2 else '',
                'localizacao': cols[3].get_text(strip=True) if len(cols) > 3 else '',
                'data_admissao': cols[5].get_text(strip=True) if len(cols) > 5 else '',
                'data_exoneracao': cols[6].get_text(strip=True) if len(cols) > 6 else '',
                'remuneracao_liquida_atual': cols[7].get_text(strip=True) if len(cols) > 7 else '',
            })

        self.log(f"Lista completa: {len(servidores)} servidores encontrados.")
        return servidores

    # ------------------------------------------------------------------
    # Meses disponíveis
    # ------------------------------------------------------------------

    def _obter_meses_disponiveis(self, servidor):
        """
        Carrega a página modal do servidor (via modal_path) e extrai as
        opções do select de meses filtradas pelo ano_limite.
        Retorna [] se não houver dados, None em caso de falha irrecuperável.
        """
        modal_path = servidor.get('modal_path')
        matricula = servidor['matricula']

        if not modal_path:
            self.log(f"  Sem modal_path para {matricula}. Pulando.")
            return []

        for tentativa in range(3):
            url = self.session_base + modal_path
            try:
                r = self.session.get(url, timeout=30)

                if r.status_code == 404:
                    self.log(f"  404 ao carregar modal de {matricula}. Renovando sessão...")
                    self._estabelecer_sessao()
                    time.sleep(2)
                    continue

                r.raise_for_status()

                soup = BeautifulSoup(r.text, 'html.parser')
                select = soup.find('select', {'id': 'myselect'})
                if not select:
                    self.log(f"  Select de meses não encontrado para {matricula}.")
                    return []

                meses = []
                for opt in select.find_all('option'):
                    texto = opt.get_text(strip=True)
                    try:
                        ano = int(texto.split('-')[1].strip())
                        if ano >= self.ano_limite:
                            meses.append(texto)
                    except Exception:
                        continue
                return meses

            except requests.exceptions.Timeout as e:
                self.log(
                    f"  Timeout ao carregar modal {matricula}: {e}. Tentando renovar sessão em 10s..."
                )
                time.sleep(10)
                try:
                    self._estabelecer_sessao()
                except Exception as sessao_err:
                    self.log(f"  Falha ao renovar sessão após timeout: {sessao_err}")

            except requests.exceptions.ConnectionError as e:
                self.log(f"  Conexão recusada ao carregar modal {matricula}: {e}. Aguardando 30s...")
                time.sleep(30)

            except requests.exceptions.RequestException as e:
                self.log(
                    f"  Erro HTTP ao carregar modal {matricula}: {e}. Nova tentativa em 10s..."
                )
                time.sleep(10)

        self.log(f"  Falha irrecuperável ao carregar modal de {matricula}.")
        return None

    # ------------------------------------------------------------------
    # Remuneração
    # ------------------------------------------------------------------

    def _obter_remuneracao(self, matricula, mes_ano):
        """
        Faz POST para Home/Pesquisar?Length=4 com a matrícula e o mês/ano
        e retorna um dict com os campos de remuneração.
        Retorna None em caso de falha irrecuperável.
        """
        for tentativa in range(3):
            url = self.session_base + "Home/Pesquisar?Length=4"
            try:
                r = self.session.post(
                    url,
                    data={'Funcionario.Matricula': matricula, 'Ano': mes_ano},
                    headers={'X-Requested-With': 'XMLHttpRequest'},
                    timeout=30,
                )

                if r.status_code == 404:
                    self.log(
                        f"  404 ao buscar remuneração {matricula} / {mes_ano}. Renovando sessão..."
                    )
                    self._estabelecer_sessao()
                    time.sleep(2)
                    continue

                r.raise_for_status()

                soup = BeautifulSoup(r.text, 'html.parser')
                dados = {}
                spans = soup.find_all('span')
                i = 0
                while i < len(spans) - 1:
                    descricao = spans[i].get_text(strip=True)
                    valor = spans[i + 1].get_text(strip=True)
                    if valor.startswith('R$') and descricao:
                        dados[descricao] = valor
                        i += 2
                        continue
                    i += 1
                return dados

            except requests.exceptions.Timeout as e:
                self.log(
                    f"  Timeout ao buscar remuneração {matricula}/{mes_ano}: {e}. Tentando renovar sessão em 10s..."
                )
                time.sleep(10)
                try:
                    self._estabelecer_sessao()
                except Exception as sessao_err:
                    self.log(f"  Falha ao renovar sessão após timeout: {sessao_err}")

            except requests.exceptions.ConnectionError as e:
                self.log(
                    f"  Conexão recusada ao buscar remuneração {matricula}/{mes_ano}: {e}. Aguardando 30s..."
                )
                time.sleep(30)

            except requests.exceptions.RequestException as e:
                self.log(
                    f"  Erro HTTP ao buscar remuneração {matricula}/{mes_ano}: {e}. Nova tentativa em 10s..."
                )
                time.sleep(10)

        self.log(f"  Falha irrecuperável ao buscar remuneração {matricula}/{mes_ano}.")
        return None

    # ------------------------------------------------------------------
    # Scrape principal
    # ------------------------------------------------------------------

    def scrape(self):
        progress = self._load_progress()
        processed_matriculas = set(progress.get('processed_matriculas', []))

        todos_servidores = self._obter_lista_servidores()

        buffer_por_mes = {}
        lote = 0
        total = 0

        for servidor in todos_servidores:
            matricula = servidor['matricula']

            if matricula in processed_matriculas:
                continue

            self.log(f"[{matricula}] {servidor['nome']}")

            meses = self._obter_meses_disponiveis(servidor)
            if meses is None:
                self.log(f"  Erro de rede. {matricula} NÃO marcado como processado.")
                continue
            if not meses:
                self.log(f"  Sem competências disponíveis >= {self.ano_limite}.")
                processed_matriculas.add(matricula)
                continue

            self.log(f"  {len(meses)} competências a extrair")

            erro_rede = False
            for mes_ano in meses:
                remuneracao = self._obter_remuneracao(matricula, mes_ano)
                if remuneracao is None:
                    self.log(
                        f"  Erro de rede na remuneração. {matricula} NÃO marcado como processado."
                    )
                    erro_rede = True
                    break

                try:
                    partes = mes_ano.split(' - ')
                    chave_arquivo = f"{partes[0].strip()}_{partes[1].strip()}"
                except Exception:
                    chave_arquivo = mes_ano.replace(' ', '').replace('-', '_')

                registro = {
                    k: v for k, v in servidor.items() if k != 'modal_path'
                }
                registro['mes_ano'] = mes_ano
                registro['remuneracao'] = remuneracao
                buffer_por_mes.setdefault(chave_arquivo, []).append(registro)
                time.sleep(0.1)

            if erro_rede:
                continue

            processed_matriculas.add(matricula)
            lote += 1
            total += 1

            if lote >= self.tamanho_lote:
                self.log(f"Salvando lote ({self.tamanho_lote} servidores)...")
                for chave, registros in buffer_por_mes.items():
                    self.save_data_merge(registros, f"tce_rj_{chave}.json", ['matricula', 'mes_ano'])
                buffer_por_mes.clear()
                lote = 0
                self._save_progress({'processed_matriculas': list(processed_matriculas)})

        if buffer_por_mes:
            self.log("Salvando dados restantes...")
            for chave, registros in buffer_por_mes.items():
                self.save_data_merge(registros, f"tce_rj_{chave}.json", ['matricula', 'mes_ano'])

        self._save_progress({'processed_matriculas': list(processed_matriculas)})
        self.log(f"Concluído. Total de servidores processados: {total}.")


if __name__ == "__main__":
    scraper = ScraperRJ()
    scraper.run()
