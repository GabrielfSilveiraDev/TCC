import re, sys, time, requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def banner(t):
    print("\n" + "="*70)
    print("  " + t)
    print("="*70)


def build_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/124.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    retry = Retry(total=3, backoff_factor=5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://",  HTTPAdapter(max_retries=retry))
    return s


SB_PAT = re.compile(r"(https?://[^/]*/portlet-portaltransparencia/[(]S[(][^)]+[)][)]/)", re.I)
IN_PAT = re.compile(r"/portlet-portaltransparencia/[(]S[(][^)]+[)][)]/")


def get_base(url):
    m = SB_PAT.match(url)
    return m.group(1) if m else None


def count_rows(soup, label):
    r = soup.select("table tbody tr")
    print("  tbody rows [%s]: %d" % (label, len(r)))
    print("  total tr  [%s]: %d" % (label, len(soup.find_all("tr"))))
    return r


PAG_HREF = re.compile(r"grid.page|SemPaginacao|pagina|pag", re.I)
PAG_TXT  = re.compile(r"grid.page|pagina", re.I)
PAG_CLS  = re.compile(r"pag|page|grid", re.I)


def pag_info(soup, label):
    print("\n  --- pagination [%s] ---" % label)
    for a in soup.find_all("a", href=True):
        h = a["href"]
        t = a.get_text(strip=True)
        if PAG_HREF.search(h) or PAG_TXT.search(t):
            print("    link href=%r  text=%r" % (h, t[:60]))
    TOT_RE = re.compile(r"(total|registros?|servidor|encontrado|[0-9]+\s*/\s*[0-9]+)", re.I)
    for tag in soup.find_all(string=TOT_RE):
        txt = tag.strip()
        if txt and len(txt) < 200:
            print("    [text] %r" % txt)
    for tag in soup.find_all(class_=PAG_CLS):
        print("    [%s] %r" % (tag.name, tag.get_text(strip=True)[:100]))
    print("  --- end [%s] ---" % label)


def form_info(soup, label):
    print("\n  --- forms [%s] ---" % label)
    for form in soup.find_all("form"):
        act = form.get("action", "?")
        mth = form.get("method", "get").upper()
        print("    action=%r method=%r" % (act, mth))
        for inp in form.find_all(["input", "select", "textarea"]):
            n  = inp.get("name", "-")
            v  = str(inp.get("value", ""))[:50]
            tp = inp.get("type", inp.name)
            print("      [%s] name=%r val=%r" % (tp, n, v))
    print("  --- end [%s] ---" % label)


# ============================================================
# STEP 1: GET portal home
# ============================================================
banner("STEP 1 - GET portal home")
URL  = "https://www.tcerj.tc.br/portlet-portaltransparencia/"
sess = build_session()
r1 = sess.get(URL, timeout=30)
print("  status=%d  url=%s" % (r1.status_code, r1.url))
base = get_base(r1.url)
if not base:
    m = IN_PAT.search(r1.text)
    if m:
        base = "https://www.tcerj.tc.br" + m.group(0)
print("  session_base=%s" % base)
if not base:
    sys.exit("ERROR: no session token found")
soup1 = BeautifulSoup(r1.text, "html.parser")
form_info(soup1, "home")
csrf = soup1.find("input", {"name": "__RequestVerificationToken"})
fd   = {"__RequestVerificationToken": csrf["value"]} if csrf else {}
print("  csrf_found=%s" % bool(csrf))


# ============================================================
# STEP 2: POST Filtrar (page 1)
# ============================================================
banner("STEP 2 - POST session_base (Filtrar page 1)")
print("  POST -> %s" % base)
r2 = sess.post(base, data=fd, timeout=30)
print("  status=%d  url=%s  bytes=%d" % (r2.status_code, r2.url, len(r2.content)))
nb = get_base(r2.url)
if nb:
    base = nb
    print("  base updated: %s" % base)
soup2 = BeautifulSoup(r2.text, "html.parser")
rows2 = count_rows(soup2, "POST-p1")
pag_info(soup2, "POST-p1")
form_info(soup2, "POST-p1")
hidden = {i["name"]: i.get("value", "") for i in soup2.find_all("input", {"type": "hidden"}) if i.get("name")}
print("  hidden fields collected: %s" % list(hidden.keys()))


# ============================================================
# STEP 3: SemPaginacao
# ============================================================
banner("STEP 3 - GET SemPaginacao")
lnk = (soup2.find("a", string=re.compile(r"Remover Pagina", re.I))
       or soup2.find("a", href=re.compile(r"SemPaginacao", re.I)))
if lnk:
    h = lnk["href"]
    sp_url = ("https://www.tcerj.tc.br" + h if h.startswith("/") else h)
    print("  link found: %s" % sp_url)
else:
    sp_url = base + "Home/SemPaginacao"
    print("  no link found, constructed: %s" % sp_url)
r3 = sess.get(sp_url, timeout=120)
print("  status=%d  url=%s  bytes=%d" % (r3.status_code, r3.url, len(r3.content)))
nb = get_base(r3.url)
if nb:
    base = nb
    print("  base updated: %s" % base)
soup3 = BeautifulSoup(r3.text, "html.parser")
rows3 = count_rows(soup3, "SemPaginacao")
pag_info(soup3, "SemPaginacao")
print("\n  --- First 10 servers (SemPaginacao) ---")
for i, row in enumerate(rows3[:10]):
    a   = row.find("a")
    mat = a.get("data-matricula", "?") if a else "?"
    nm  = a.get_text(strip=True)[:55] if a else "?"
    print("    [%02d] mat=%-14r  %r" % (i+1, mat, nm))


# ============================================================
# STEP 3b: All unique links on SemPaginacao
# ============================================================
banner("STEP 3b - All unique links on SemPaginacao page")
seen = set()
for a in soup3.find_all("a", href=True):
    key = (a["href"], a.get_text(strip=True)[:40])
    if key not in seen:
        seen.add(key)
        print("  href=%-55r  text=%r" % (key[0], key[1]))


# ============================================================
# STEP 3c: All inputs/selects/buttons on SemPaginacao
# ============================================================
banner("STEP 3c - All inputs/selects/buttons in SemPaginacao")
for inp in soup3.find_all(["input", "select", "button"]):
    n  = inp.get("name", "-")
    v  = str(inp.get("value", ""))[:50]
    tp = inp.get("type", inp.name)
    print("  [%s] name=%r  val=%r" % (tp, n, v))
form_info(soup3, "SemPaginacao")


# ============================================================
# STEP 4: POST ?grid-page=2
# ============================================================
banner("STEP 4 - POST ?grid-page=2")
p2u = base + "?grid-page=2"
print("  POST -> %s" % p2u)
print("  data  -> %s" % hidden)
r4 = sess.post(p2u, data=hidden, timeout=30)
print("  status=%d  url=%s  bytes=%d" % (r4.status_code, r4.url, len(r4.content)))
soup4 = BeautifulSoup(r4.text, "html.parser")
rows4 = count_rows(soup4, "grid-page=2")
pag_info(soup4, "grid-page=2")
if rows4:
    print("\n  --- First 5 servers page 2 ---")
    for i, row in enumerate(rows4[:5]):
        a   = row.find("a")
        mat = a.get("data-matricula", "?") if a else "?"
        nm  = a.get_text(strip=True)[:55] if a else "?"
        print("    [%d] mat=%-14r  %r" % (i+1, mat, nm))


# ============================================================
# STEP 5: Probe pages 3..15 POST
# ============================================================
banner("STEP 5 - Probe pages 3..15 POST ?grid-page=N")
for pn in range(3, 16):
    rp  = sess.post(base + ("?grid-page=%d" % pn), data=hidden, timeout=30)
    sp  = BeautifulSoup(rp.text, "html.parser")
    rws = sp.select("table tbody tr")
    ttr = len(sp.find_all("tr"))
    print("  page %2d: status=%d  tbody=%4d  tr=%4d  bytes=%d" % (pn, rp.status_code, len(rws), ttr, len(rp.content)))
    if not rws:
        print("         -> empty page %d, stop." % pn)
        break
    time.sleep(0.4)


# ============================================================
# STEP 6: Probe pages 2..5 GET
# ============================================================
banner("STEP 6 - Probe pages 2..5 GET ?grid-page=N")
for pn in range(2, 6):
    rp  = sess.get(base + ("?grid-page=%d" % pn), timeout=30)
    sp  = BeautifulSoup(rp.text, "html.parser")
    rws = sp.select("table tbody tr")
    print("  GET page %d: status=%d  tbody=%4d  bytes=%d" % (pn, rp.status_code, len(rws), len(rp.content)))
    time.sleep(0.3)


# ============================================================
# STEP 7: Keyword context in SemPaginacao HTML
# ============================================================
banner("STEP 7 - Keyword context in SemPaginacao HTML")
t3 = r3.text
for kw in ["total", "Total", "registros", "Registros", "grid-page",
           "paginacao", "Paginacao", "SemPaginacao", "encontrado", "servidor"]:
    ix = t3.find(kw)
    if ix != -1:
        s = t3[max(0, ix-80):ix+140].replace("\n", " ").replace("\r", "")
        print("  kw=%r" % kw)
        print("  ctx=%r" % s)


# ============================================================
# STEP 8: Keyword context in POST page-1 HTML
# ============================================================
banner("STEP 8 - Keyword context in POST page-1 HTML")
t2 = r2.text
for kw in ["grid-page", "__VIEWSTATE", "totalPages", "totalCount",
           "pageSize", "pageCount", "registros", "total"]:
    ix = t2.find(kw)
    if ix != -1:
        s = t2[max(0, ix-60):ix+140].replace("\n", " ").replace("\r", "")
        print("  kw=%r" % kw)
        print("  ctx=%r" % s)


banner("DONE")
