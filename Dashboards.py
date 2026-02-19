import pandas as pd
import json
import streamlit as st
import plotly.express as px

# --- Utils ---
def parse_valor(v):
    return float(v.replace('.', '').replace(',', '.')) if v else 0.0

def load_dados(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def preparar_dataframe(data):
    df = pd.json_normalize(data)
    df["salario_liquido"] = df["salario_liquido"].apply(parse_valor)
    df["total_proventos"] = df["total_proventos"].apply(parse_valor)
    df["total_descontos"] = df["total_descontos"].apply(parse_valor)
    return df

def preparar_proventos(data):
    proventos_data = []
    for s in data:
        for p in s["proventos"]:
            proventos_data.append({
                "nome": s["nome"],
                "cargo": s["cargo"],
                "tipo": s["tipo"],
                "descricao": p["descricao"],
                "valor": parse_valor(p["valor"])
            })
    return pd.DataFrame(proventos_data)

def aplicar_filtros(df, tipo_opcao, faixa, nome_filtro, cargo_filtro):
    df_filtrado = df[
        (df["salario_liquido"] >= faixa[0]) & (df["salario_liquido"] <= faixa[1])
    ]
    if nome_filtro:
        df_filtrado = df_filtrado[df_filtrado["nome"].str.contains(nome_filtro, case=False)]
    if cargo_filtro != "Todos":
        df_filtrado = df_filtrado[df_filtrado["cargo"] == cargo_filtro]
    if tipo_opcao != "Todos":
        df_filtrado = df_filtrado[df_filtrado["tipo"] == tipo_opcao]
    return df_filtrado

def pagina_analise(nome_tce, df, df_proventos, tipo_opcao, faixa, nome_filtro, cargo_filtro):
    st.title(f"📊 Painel de Análise - {nome_tce}")
    df_filtrado = aplicar_filtros(df, tipo_opcao, faixa, nome_filtro, cargo_filtro)

    st.subheader("⚔️ Comparativo - Ativos vs Inativos")
    media_por_tipo = df.groupby("tipo")["salario_liquido"].mean().reset_index()
    fig_tipo = px.bar(media_por_tipo, x="tipo", y="salario_liquido", color="tipo", title="Média Salarial por Tipo")
    st.plotly_chart(fig_tipo, use_container_width=True)

    st.subheader("📊 Distribuição Salarial por Faixa")
    bins = [0, 5000, 10000, 15000, 20000, 30000, 50000]
    labels = ["0-5k", "5k-10k", "10k-15k", "15k-20k", "20k-30k", "30k+"]
    df_filtrado["faixa_salarial"] = pd.cut(df_filtrado["salario_liquido"], bins=bins, labels=labels)
    faixa_df = df_filtrado["faixa_salarial"].value_counts().sort_index().reset_index()
    faixa_df.columns = ["faixa", "quantidade"]
    fig_hist = px.bar(faixa_df, x="faixa", y="quantidade", color="faixa", title="Distribuição de Salários")
    st.plotly_chart(fig_hist, use_container_width=True)

    st.subheader("🏆 Top 10 salários (filtrados)")
    top = df_filtrado.sort_values("salario_liquido", ascending=False).head(10)
    fig_top = px.bar(top, x="nome", y="salario_liquido", color="nome", title="Top 10 Salários")
    st.plotly_chart(fig_top, use_container_width=True)

    st.subheader("💼 Bonificações mais frequentes")
    bonif_freq_df = df_proventos["descricao"].value_counts().reset_index()
    bonif_freq_df.columns = ["descricao", "frequencia"]
    fig_freq = px.bar(bonif_freq_df.head(10), x="descricao", y="frequencia", color="descricao")
    st.plotly_chart(fig_freq, use_container_width=True)

    st.subheader("💸 Bonificações com maior valor médio")
    bonif_valor_df = df_proventos.groupby("descricao")["valor"].mean().reset_index()
    bonif_valor_df = bonif_valor_df.sort_values("valor", ascending=False).head(10)
    fig_valor = px.bar(bonif_valor_df, x="descricao", y="valor", color="descricao")
    st.plotly_chart(fig_valor, use_container_width=True)

    st.subheader("📚 Total de Bonificações, Descontos e Salário Líquido por Servidor")
    filtrados = df_proventos[df_proventos["nome"].isin(df_filtrado["nome"])]
    bonif_por_servidor = filtrados.groupby(["nome", "cargo", "tipo"])["valor"].sum().reset_index()
    bonif_por_servidor = bonif_por_servidor.rename(columns={"valor": "total_bonificacoes"})
    df_info = df_filtrado[["nome", "total_descontos", "salario_liquido"]]
    tabela_final = pd.merge(bonif_por_servidor, df_info, on="nome", how="left")
    tabela_final = tabela_final.sort_values("total_bonificacoes", ascending=False)
    st.dataframe(tabela_final)

    st.subheader("🔍 Detalhamento por bonificação")
    bonus_escolhido = st.selectbox("Escolha a bonificação", df_proventos["descricao"].unique())
    df_bonificado = df_proventos[df_proventos["descricao"] == bonus_escolhido].sort_values("valor", ascending=False)
    st.dataframe(df_bonificado)

    st.sidebar.download_button("📥 Baixar dados filtrados (CSV)", df_filtrado.to_csv(index=False), file_name=f"{nome_tce.lower().replace('/', '')}_filtrado.csv")

def pagina_comparativa(df_sc, df_sp, tipo_opcao, faixa, nome_filtro, cargo_filtro):
    st.title("⚖️ Comparativo Geral - TCE-SC vs TCE-SP")

    df_sc_f = aplicar_filtros(df_sc, tipo_opcao, faixa, nome_filtro, cargo_filtro)
    df_sp_f = aplicar_filtros(df_sp, tipo_opcao, faixa, nome_filtro, cargo_filtro)

    resumo = pd.DataFrame({
        "TCE": ["SC", "SP"],
        "Total de Servidores": [len(df_sc_f), len(df_sp_f)],
        "Gasto Total com Servidores": [df_sc_f["salario_liquido"].sum(), df_sp_f["salario_liquido"].sum()],
        "Média Salarial": [df_sc_f["salario_liquido"].mean(), df_sp_f["salario_liquido"].mean()],
        "Total Proventos": [df_sc_f["total_proventos"].sum(), df_sp_f["total_proventos"].sum()],
        "Total Descontos": [df_sc_f["total_descontos"].sum(), df_sp_f["total_descontos"].sum()],
        "Benefícios per capita": [
            df_sc_f["total_proventos"].sum() / len(df_sc_f) if len(df_sc_f) else 0,
            df_sp_f["total_proventos"].sum() / len(df_sp_f) if len(df_sp_f) else 0
        ],
        "Descontos per capita": [
            df_sc_f["total_descontos"].sum() / len(df_sc_f) if len(df_sc_f) else 0,
            df_sp_f["total_descontos"].sum() / len(df_sp_f) if len(df_sp_f) else 0
        ]
    })

    resumo["Gasto Total com Servidores"] = resumo["Gasto Total com Servidores"].round(2)
    resumo["Média Salarial"] = resumo["Média Salarial"].round(2)

    resumo["TCE_Gasto"] = resumo.apply(
        lambda row: f"{row['TCE']} - R$ {row['Gasto Total com Servidores']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        axis=1
    )
    resumo["TCE_Media"] = resumo.apply(
        lambda row: f"{row['TCE']} - R$ {row['Média Salarial']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        axis=1
    )

    fig = px.bar(
        resumo,
        x="TCE_Gasto",
        y="Gasto Total com Servidores",
        color="TCE",
        title="Gasto Total com Servidores"
    )
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.bar(
        resumo,
        x="TCE_Media",
        y="Média Salarial",
        color="TCE",
        title="Média Salarial por TCE"
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("💰 Comparativo de Bonificações por TCE (per capita)")

    # Aplica filtros nos proventos
    prov_sc_f = df_prov_sc[df_prov_sc["nome"].isin(df_sc_f["nome"])]
    prov_sp_f = df_prov_sp[df_prov_sp["nome"].isin(df_sp_f["nome"])]

    # Bonificações disponíveis (interseção para garantir que existam nos dois)
    bonificacoes_disponiveis = sorted(
        list(set(prov_sc_f["descricao"].unique()) & set(prov_sp_f["descricao"].unique()))
    )

    bonificacao_escolhida = st.selectbox("Escolha a bonificação para comparar", bonificacoes_disponiveis)

    total_sc = prov_sc_f[prov_sc_f["descricao"] == bonificacao_escolhida]["valor"].sum()
    total_sp = prov_sp_f[prov_sp_f["descricao"] == bonificacao_escolhida]["valor"].sum()

    per_capita_sc = total_sc / len(df_sc_f) if len(df_sc_f) else 0
    per_capita_sp = total_sp / len(df_sp_f) if len(df_sp_f) else 0

    bonif_df = pd.DataFrame({
        "TCE": ["SC", "SP"],
        "Gasto per capita (R$)": [round(per_capita_sc, 2), round(per_capita_sp, 2)]
    })

    fig_bonus = px.bar(
        bonif_df,
        x="TCE",
        y="Gasto per capita (R$)",
        color="TCE",
        title=f"Gasto per capita com '{bonificacao_escolhida}'"
    )
    st.plotly_chart(fig_bonus, use_container_width=True)


# --- Main ---
st.set_page_config(layout="wide")

data_sc = load_dados("servidores_tce_sc_estruturado.json")
data_sp = load_dados("servidores_tce_sp_estruturado.json")

df_sc = preparar_dataframe(data_sc)
df_sp = preparar_dataframe(data_sp)
df_prov_sc = preparar_proventos(data_sc)
df_prov_sp = preparar_proventos(data_sp)

# Sidebar Filtros
st.sidebar.header("🔎 Filtros")
tipo_opcao = st.sidebar.selectbox("Tipo de Servidor", ["Todos", "ATIVO", "INATIVO"])
faixa = st.sidebar.slider("Faixa Salarial (R$)", float(min(df_sc["salario_liquido"].min(), df_sp["salario_liquido"].min())),
                          float(max(df_sc["salario_liquido"].max(), df_sp["salario_liquido"].max())),
                          (float(min(df_sc["salario_liquido"].min(), df_sp["salario_liquido"].min())),
                           float(max(df_sc["salario_liquido"].max(), df_sp["salario_liquido"].max()))))
nome_filtro = st.sidebar.text_input("Buscar por nome")
cargos = sorted(set(df_sc["cargo"].dropna().unique()).union(df_sp["cargo"].dropna().unique()))
cargo_filtro = st.sidebar.selectbox("Cargo", ["Todos"] + cargos)

pagina = st.sidebar.radio("Escolha a Página", ["TCE-SC", "TCE-SP", "Comparativo"])

if pagina == "TCE-SC":
    pagina_analise("TCE/SC", df_sc, df_prov_sc, tipo_opcao, faixa, nome_filtro, cargo_filtro)
elif pagina == "TCE-SP":
    pagina_analise("TCE/SP", df_sp, df_prov_sp, tipo_opcao, faixa, nome_filtro, cargo_filtro)
else:
    pagina_comparativa(df_sc, df_sp, tipo_opcao, faixa, nome_filtro, cargo_filtro)