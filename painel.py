"""
Painel Geral: visão visual de contratos, fiscais, vencimentos e pedidos.
"""

import os
import sys
from datetime import date

import pandas as pd  # type: ignore
import plotly.express as px  # type: ignore
import streamlit as st  # type: ignore

from database import PASTA_PROJETO
from queries_contratos import FAIXAS_VENCIMENTO, listar_contratos
from queries_itens import contagem_itens_por_contrato
from resumo_semanal import (
    FAIXAS_EXIBIDAS,
    ICONES,
    gerar_excel,
    gerar_html,
    gerar_texto,
    montar_resumo,
    salvar_arquivos,
)
from queries_pedidos import (
    calcular_kpis_pedidos,
    listar_pedidos,
    normalizar_arp,
    resumo_por_arp,
)

# Constantes para evitar duplicação de literais (S1192)
FAIXA_VENCIDO = "Vencido"
FAIXA_ATE_30 = "Até 30 dias"
FAIXA_31_60 = "31 a 60 dias"
FAIXA_61_90 = "61 a 90 dias"
FAIXA_ACIMA_90 = "Acima de 90 dias"
FAIXA_SEM_DATA = "Sem data definida"

TIPO_ARP = "Ata de registro de preços"
STATUS_EM_ANDAMENTO = "Em andamento"
ROTULO_SITUACAO = "Situação"

CORES_FAIXA = {
    FAIXA_VENCIDO: "#A32D2D",
    FAIXA_ATE_30: "#E24B4A",
    FAIXA_31_60: "#EF9F27",
    FAIXA_61_90: "#E8D34A",
    FAIXA_ACIMA_90: "#5DCAA5",
    FAIXA_SEM_DATA: "#9AA0A6",
}

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _data(serie: pd.Series) -> pd.Series:
    return serie.dt.strftime("%d/%m/%Y").fillna("—")


def _tabela_contratos(sub: pd.DataFrame, ordenar_por_prazo: bool = True):
    """Tabela padrão de contratos usada nas listas do painel."""
    if ordenar_por_prazo:
        sub = sub.sort_values("dias_para_vencer", na_position="last")
    tabela = pd.DataFrame(
        {
            "Tipo": sub["tipo"].replace({TIPO_ARP: "ARP"}),
            "Nº": sub["numero_contrato"],
            "Fornecedor": sub["razao_social"],
            "Objeto": sub["objeto"],
            "Vencimento": _data(sub["data_fim"]),
            "Dias": sub["dias_para_vencer"].astype("Int64"),
            "Fiscal": sub["fiscal"].fillna("—"),
        }
    )
    st.dataframe(tabela, width="stretch", hide_index=True)


def _grafico_layout(fig, altura=340):
    fig.update_layout(
        height=altura,
        margin={"l": 10, "r": 10, "t": 40, "b": 10},
        legend_title_text="",
    )
    return fig


def _aba_gantt(df: pd.DataFrame, hoje: pd.Timestamp):
    """Gantt dos contratos que vencem primeiro, com as faixas de 30/60/90 dias ao fundo."""
    st.caption(
        "Contratos que vencem primeiro, do mais próximo ao mais distante. "
        "As faixas coloridas ao fundo marcam os próximos 30, 60 e 90 dias a partir de hoje."
    )
    c1, c2 = st.columns([3, 1])
    qtd = c1.slider("Quantos contratos mostrar", 5, 40, 15)
    incluir_vencidos = c2.checkbox("Incluir vencidos", value=False)

    com_fim = df[df["data_fim"].notna()]
    base = com_fim[com_fim["data_inicio"].notna()]
    if not incluir_vencidos:
        base = base[base["data_fim"] >= hoje]
    base = base.sort_values("data_fim").head(qtd).copy()

    sem_inicio = len(com_fim) - len(com_fim[com_fim["data_inicio"].notna()])
    if sem_inicio:
        st.caption(f"{sem_inicio} contrato(s) sem data de início não aparecem no gráfico.")
    if base.empty:
        st.info("Nenhum contrato com datas completas para mostrar.")
        return

    base["Contrato"] = (
        base["tipo"].replace({TIPO_ARP: "ARP"})
        + " "
        + base["numero_contrato"]
        + " — "
        + base["razao_social"].str.slice(0, 28)
    )
    duplicados = base["Contrato"].duplicated(keep=False)
    base.loc[duplicados, "Contrato"] += " (#" + base.loc[duplicados, "id"].astype(str) + ")"

    base["Vencimento"] = _data(base["data_fim"])
    base["Dias"] = base["dias_para_vencer"].astype("Int64").astype(str)
    base["Fiscal"] = base["fiscal"].fillna("—")

    fig = px.timeline(
        base,
        x_start="data_inicio",
        x_end="data_fim",
        y="Contrato",
        color="faixa_vencimento",
        color_discrete_map=CORES_FAIXA,
        category_orders={"Contrato": base["Contrato"].tolist()},
        hover_name="Contrato",
        hover_data={
            "razao_social": True,
            "objeto": True,
            "Vencimento": True,
            "Dias": True,
            "Fiscal": True,
            "data_inicio": False,
            "data_fim": False,
            "faixa_vencimento": False,
            "Contrato": False,
        },
        labels={"razao_social": "Fornecedor", "objeto": "Objeto", "faixa_vencimento": ""},
    )
    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)

    def dia(n_dias):
        return (hoje + pd.Timedelta(days=n_dias)).strftime("%Y-%m-%d")

    for ini, fim, cor, rotulo in [
        (0, 30, "#E24B4A", "30 dias"),
        (30, 60, "#EF9F27", "60 dias"),
        (60, 90, "#E8D34A", "90 dias"),
    ]:
        fig.add_vrect(x0=dia(ini), x1=dia(fim), fillcolor=cor, opacity=0.12, line_width=0, layer="below")
        fig.add_annotation(
            x=dia(fim), y=1.0, yref="paper", yanchor="bottom", text=rotulo,
            showarrow=False, font={"size": 11},
        )
    fig.add_shape(
        type="line", x0=dia(0), x1=dia(0), y0=0, y1=1, yref="paper",
        line={"color": "#888888", "width": 2, "dash": "dash"},
    )
    fig.add_annotation(
        x=dia(0), y=1.0, yref="paper", yanchor="bottom", xanchor="right", text="Hoje ",
        showarrow=False, font={"size": 11},
    )

    limite_dir = max(base["data_fim"].max(), hoje + pd.Timedelta(days=95)) + pd.Timedelta(days=15)
    fig.update_xaxes(range=[(hoje - pd.Timedelta(days=150)).strftime("%Y-%m-%d"), limite_dir.strftime("%Y-%m-%d")])
    fig.update_layout(
        height=140 + 32 * len(base),
        margin={"l": 10, "r": 10, "t": 50, "b": 10},
        legend_title_text="",
        legend={"orientation": "h", "y": -0.08},
    )
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# Funções de decomposição para reduzir Complexidade Cognitiva (S3776)
# ---------------------------------------------------------------------------
def _aba_vencimentos(df: pd.DataFrame, hoje: pd.Timestamp):
    c1, c2 = st.columns(2)
    with c1:
        por_faixa = (
            df["faixa_vencimento"]
            .value_counts()
            .reindex(FAIXAS_VENCIMENTO, fill_value=0)
            .reset_index()
        )
        por_faixa.columns = ["Faixa", "Contratos"]
        fig = px.bar(
            por_faixa,
            x="Faixa",
            y="Contratos",
            color="Faixa",
            color_discrete_map=CORES_FAIXA,
            text="Contratos",
            title="Contratos por faixa de vencimento",
        )
        fig.update_layout(showlegend=False, xaxis_title=None)
        st.plotly_chart(_grafico_layout(fig), width="stretch")

    with c2:
        meses = pd.period_range(hoje.to_period("M"), periods=12, freq="M")
        futuros = df[df["data_fim"].notna() & (df["data_fim"] >= hoje)]
        por_mes = futuros["data_fim"].dt.to_period("M").value_counts()
        mensal = pd.DataFrame(
            {
                "Mês": [f"{MESES[p.month - 1]}/{str(p.year)[2:]}" for p in meses],
                "Contratos": [int(por_mes.get(p, 0)) for p in meses],
            }
        )
        fig = px.bar(
            mensal,
            x="Mês",
            y="Contratos",
            text="Contratos",
            title="Vencimentos nos próximos 12 meses",
        )
        fig.update_traces(marker_color="#378ADD")
        fig.update_layout(xaxis_title=None)
        st.plotly_chart(_grafico_layout(fig), width="stretch")

    st.subheader("Quais contratos estão em cada faixa")
    for faixa, icone, aberto in [
        (FAIXA_VENCIDO, "🔴", True),
        (FAIXA_ATE_30, "🟠", True),
        (FAIXA_31_60, "🟡", False),
        (FAIXA_61_90, "🟢", False),
    ]:
        sub = df[df["faixa_vencimento"] == faixa]
        titulo = f"{icone} {faixa} — {len(sub)} contrato(s)"
        with st.expander(titulo, expanded=aberto and len(sub) > 0):
            if sub.empty:
                st.write("Nenhum contrato nesta faixa.")
            else:
                _tabela_contratos(sub)


def _aba_fiscais(df: pd.DataFrame):
    df_f = df.copy()
    df_f["fiscal"] = df_f["fiscal"].fillna("(sem fiscal)")

    ordem = df_f["fiscal"].value_counts().index.tolist()
    agrupado = (
        df_f.groupby(["fiscal", "faixa_vencimento"]).size().reset_index(name="Contratos")
    )
    fig = px.bar(
        agrupado,
        y="fiscal",
        x="Contratos",
        color="faixa_vencimento",
        orientation="h",
        color_discrete_map=CORES_FAIXA,
        category_orders={"fiscal": ordem[::-1], "faixa_vencimento": FAIXAS_VENCIMENTO},
        title="Contratos por fiscal (cor = situação do vencimento)",
        labels={"fiscal": "", "faixa_vencimento": ""},
    )
    st.plotly_chart(_grafico_layout(fig, altura=max(320, 55 * len(ordem))), width="stretch")

    resumo = (
        df_f.pivot_table(
            index="fiscal",
            columns="faixa_vencimento",
            values="id",
            aggfunc="count",
            fill_value=0,
        )
        .reindex(columns=FAIXAS_VENCIMENTO, fill_value=0)
    )
    resumo["Total"] = resumo.sum(axis=1)
    resumo = resumo.sort_values("Total", ascending=False)
    resumo.index.name = "Fiscal"
    resumo.columns.name = None
    st.dataframe(
        resumo[["Total", FAIXA_VENCIDO, FAIXA_ATE_30, FAIXA_31_60, FAIXA_61_90, FAIXA_ACIMA_90]],
        width="stretch",
    )

    st.subheader("Contratos de um fiscal")
    escolha = st.selectbox("Fiscal", ["Todos"] + ordem)
    sub = df_f if escolha == "Todos" else df_f[df_f["fiscal"] == escolha]
    _tabela_contratos(sub)


def _aba_fornecedores(df: pd.DataFrame):
    c1, c2 = st.columns(2)
    with c1:
        por_tipo = df["tipo"].value_counts().reset_index()
        por_tipo.columns = ["Tipo", "Quantidade"]
        fig = px.pie(
            por_tipo, names="Tipo", values="Quantidade", hole=0.5,
            title="Contratos x Atas de registro de preços",
        )
        st.plotly_chart(_grafico_layout(fig), width="stretch")

    with c2:
        top = df["razao_social"].value_counts().head(10).reset_index()
        top.columns = ["Fornecedor", "Contratos"]
        fig = px.bar(
            top.iloc[::-1], x="Contratos", y="Fornecedor", orientation="h",
            text="Contratos", title="Fornecedores com mais contratos/atas",
        )
        fig.update_traces(marker_color="#7F77DD")
        fig.update_layout(yaxis_title=None)
        st.plotly_chart(_grafico_layout(fig), width="stretch")


def _renderizar_grafico_pedidos_arp(com_pedidos: pd.DataFrame):
    grafico = pd.DataFrame(
        {
            "ARP": com_pedidos["arp"] + " — " + com_pedidos["fornecedor"].str.slice(0, 24),
            "Atrasado": com_pedidos["atrasados"],
            STATUS_EM_ANDAMENTO: com_pedidos["abertos"] - com_pedidos["atrasados"],
            "Entregue": com_pedidos["entregues"],
            "Cancelado": com_pedidos["pedidos"] - com_pedidos["abertos"] - com_pedidos["entregues"],
        }
    ).melt(id_vars="ARP", var_name=ROTULO_SITUACAO, value_name="Pedidos")
    grafico = grafico[grafico["Pedidos"] > 0]
    fig = px.bar(
        grafico, y="ARP", x="Pedidos", color=ROTULO_SITUACAO, orientation="h",
        color_discrete_map={
            "Atrasado": "#E24B4A", STATUS_EM_ANDAMENTO: "#EF9F27",
            "Entregue": "#5DCAA5", "Cancelado": "#9AA0A6",
        },
        category_orders={ROTULO_SITUACAO: ["Atrasado", STATUS_EM_ANDAMENTO, "Entregue", "Cancelado"]},
        title="Pedidos por ARP e situação", labels={"ARP": ""},
    )
    st.plotly_chart(_grafico_layout(fig, altura=max(300, 60 * len(com_pedidos))), width="stretch")


def _renderizar_detalhes_arp(resumo: pd.DataFrame, pedidos: pd.DataFrame):
    def observacao(r):
        if not r["cadastrada"]:
            return "ARP não encontrada nos contratos"
        if r["arquivada"]:
            return "ARP arquivada"
        return "Sem pedidos" if r["pedidos"] == 0 else ""

    tabela = pd.DataFrame(
        {
            "ARP": resumo["arp"],
            "Fornecedor": resumo["fornecedor"],
            "Vencimento da ARP": _data(pd.to_datetime(resumo["vencimento_arp"])),
            "Pedidos": resumo["pedidos"],
            "Em aberto": resumo["abertos"],
            "Atrasados": resumo["atrasados"],
            "Entregues": resumo["entregues"],
            "Próximo prazo": _data(pd.to_datetime(resumo["proximo_prazo"])),
            "Observação": resumo.apply(observacao, axis=1),
        }
    ).sort_values(["Atrasados", "Pedidos"], ascending=False)
    st.dataframe(tabela, width="stretch", hide_index=True)

    st.markdown("**Ver os pedidos de uma ARP**")
    opcoes = {f"{r.arp} — {r.fornecedor}": r.chave for r in resumo.itertuples()}
    escolha = st.selectbox("ARP", list(opcoes.keys()), label_visibility="collapsed")
    sub = pedidos[pedidos["arp"].map(normalizar_arp) == opcoes[escolha]] if not pedidos.empty else pedidos
    if sub.empty:
        st.caption("Nenhum pedido registrado para esta ARP.")
    else:
        st.dataframe(
            pd.DataFrame(
                {
                    "SIC": sub["sic"],
                    "Nº do pedido": sub["numero_pedido"],
                    "Data de envio": _data(sub["data_envio"]),
                    "Prazo": _data(sub["prazo"]),
                    "Restante (dias)": sub["dias_restantes"],
                    ROTULO_SITUACAO: sub["status_calculado"],
                }
            ),
            width="stretch",
            hide_index=True,
        )


def _aba_pedidos():
    pedidos = listar_pedidos()
    if pedidos.empty:
        st.info("Nenhum pedido cadastrado ainda.")
    else:
        kp = calcular_kpis_pedidos(pedidos)
        p1, p2, p3 = st.columns(3)
        p1.metric("🔴 Atrasados", kp["atrasados"], border=True)
        p2.metric("🟡 Em andamento", kp["em_andamento"], border=True)
        p3.metric("🟢 Entregues", kp["entregues"], border=True)

    todos = listar_contratos(incluir_arquivados=True)
    arps = todos[todos["tipo"] == TIPO_ARP]
    resumo = resumo_por_arp(pedidos, arps)
    if not resumo.empty:
        resumo = resumo[(resumo["pedidos"] > 0) | (resumo["arquivada"] == 0)]

    st.subheader("Pedidos de cada ARP")
    if resumo.empty:
        st.write("Nenhuma ARP cadastrada.")
    else:
        com_pedidos = resumo[resumo["pedidos"] > 0]
        if com_pedidos.empty:
            st.info("Ainda não há pedidos vinculados às ARPs. Cadastre em Cadastros > Pedidos.")
        else:
            _renderizar_grafico_pedidos_arp(com_pedidos)
        _renderizar_detalhes_arp(resumo, pedidos)

    if not pedidos.empty:
        abertos = pedidos[~pedidos["status_calculado"].isin(["Entregue", "Cancelado"])]
        st.subheader("Pedidos em aberto, do mais urgente ao menos urgente")
        if abertos.empty:
            st.write("Nenhum pedido em aberto.")
        else:
            abertos = abertos.sort_values("dias_restantes", na_position="last")
            st.dataframe(
                pd.DataFrame(
                    {
                        "ARP": abertos["arp"],
                        "Fornecedor": abertos["fornecedor"],
                        "SIC": abertos["sic"],
                        "Nº do pedido": abertos["numero_pedido"],
                        "Prazo": _data(abertos["prazo"]),
                        "Restante (dias)": abertos["dias_restantes"],
                        ROTULO_SITUACAO: abertos["status_calculado"],
                    }
                ),
                width="stretch",
                hide_index=True,
            )


def _aba_pendencias(df: pd.DataFrame):
    itens = contagem_itens_por_contrato()
    com_itens = set(itens["contrato_id"]) if not itens.empty else set()
    df["tem_itens"] = df["id"].isin(com_itens)

    feitos = int(df["tem_itens"].sum())
    st.subheader("Itens dos contratos cadastrados")
    st.progress(feitos / len(df), text=f"{feitos} de {len(df)} contratos com itens cadastrados")

    sem_itens = df[~df["tem_itens"]]
    with st.expander(f"Contratos ainda sem itens ({len(sem_itens)})"):
        if sem_itens.empty:
            st.write("Todos os contratos têm itens cadastrados. 🎉")
        else:
            _tabela_contratos(sem_itens)

    sem_data = df[df["data_fim"].isna()]
    with st.expander(f"Contratos sem data de vencimento ({len(sem_data)})"):
        if sem_data.empty:
            st.write("Nenhum.")
        else:
            _tabela_contratos(sem_data, ordenar_por_prazo=False)

    sem_fiscal = df[df["fiscal"].isna()]
    with st.expander(f"Contratos sem fiscal ({len(sem_fiscal)})"):
        if sem_fiscal.empty:
            st.write("Nenhum.")
        else:
            _tabela_contratos(sem_fiscal)


# ---------------------------------------------------------------------------
# Página: Painel Geral
# ---------------------------------------------------------------------------
def pagina_painel_geral():
    st.title("Painel Geral — Contratos e Atas de TI")
    df = listar_contratos()

    if df.empty:
        st.info(
            "Nenhum contrato no sistema ainda. Rode `python import_contratos.py "
            "sua_planilha.xlsx` ou cadastre pela página 'Cadastros'."
        )
        return

    hoje = pd.Timestamp(date.today())
    st.caption(f"Posição em {hoje:%d/%m/%Y} — os prazos são recalculados todo dia automaticamente.")

    df = df.copy()
    df["fiscal"] = df["fiscal"].replace("", pd.NA)
    contagem = df["faixa_vencimento"].value_counts()

    def n(faixa):
        return int(contagem.get(faixa, 0))

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Contratos e atas", len(df), border=True)
    k2.metric("🔴 Vencidos", n(FAIXA_VENCIDO), border=True)
    k3.metric("🟠 Vencem em até 30 dias", n(FAIXA_ATE_30), border=True)
    k4.metric("🟡 De 31 a 60 dias", n(FAIXA_31_60), border=True)
    k5.metric("🟢 De 61 a 90 dias", n(FAIXA_61_90), border=True)

    aba_venc, aba_gantt, aba_fiscal, aba_forn, aba_ped, aba_pend = st.tabs(
        [
            "⏳ Vencimentos",
            "📅 Linha do tempo",
            "👤 Fiscais",
            "🏢 Fornecedores e tipos",
            "📦 Pedidos",
            "🧹 Pendências",
        ]
    )

    with aba_venc:
        _aba_vencimentos(df, hoje)
    with aba_gantt:
        _aba_gantt(df, hoje)
    with aba_fiscal:
        _aba_fiscais(df)
    with aba_forn:
        _aba_fornecedores(df)
    with aba_ped:
        _aba_pedidos()
    with aba_pend:
        _aba_pendencias(df)


# ---------------------------------------------------------------------------
# Subfunções da Página de Resumo Semanal (reduzir S3776)
# ---------------------------------------------------------------------------
def _renderizar_bloco_downloads(resumo: dict, hoje: pd.Timestamp):
    st.divider()
    st.subheader("Levar o resumo para fora do sistema")
    d1, d2, d3 = st.columns(3)
    sufixo = f"{hoje:%Y-%m-%d}"
    d1.download_button(
        "⬇️ Excel (uma aba por faixa)",
        data=gerar_excel(resumo),
        file_name=f"Resumo_Contratos_{sufixo}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
    d2.download_button(
        "⬇️ HTML (imprimir ou colar no e-mail)",
        data=gerar_html(resumo),
        file_name=f"Resumo_Contratos_{sufixo}.html",
        mime="text/html",
        width="stretch",
    )
    d3.download_button(
        "⬇️ Texto simples",
        data=gerar_texto(resumo),
        file_name=f"Resumo_Contratos_{sufixo}.txt",
        mime="text/plain",
        width="stretch",
    )
    st.markdown("**Mensagem pronta para copiar** (Teams, e-mail, WhatsApp) — use o ícone de copiar no canto do quadro:")
    st.code(gerar_texto(resumo), language=None)


def _renderizar_bloco_agendamento(resumo: dict):
    with st.expander("⏰ Receber automaticamente toda semana (Windows)"):
        st.write(
            "O script `gerar_resumo_semanal.py` cria os três arquivos na pasta `resumos/` do projeto. "
            "Para ele rodar sozinho toda segunda-feira às 08:00, abra o **Prompt de Comando** "
            "e cole o comando abaixo (já com os caminhos deste computador):"
        )
        script = os.path.join(PASTA_PROJETO, "gerar_resumo_semanal.py")
        comando = (
            f'schtasks /create /tn "Resumo Semanal Contratos" '
            f'/tr "\\"{sys.executable}\\" \\"{script}\\"" /sc weekly /d MON /st 08:00'
        )
        st.code(comando, language="bat")
        st.caption(
            "Para remover: `schtasks /delete /tn \"Resumo Semanal Contratos\" /f`. "
            "O computador precisa estar ligado no horário agendado."
        )
        if st.button("Gerar os arquivos agora na pasta resumos/"):
            caminhos = salvar_arquivos(resumo)
            st.success("Arquivos gerados:")
            for caminho in caminhos.values():
                st.code(caminho, language=None)


# ---------------------------------------------------------------------------
# Funções auxiliares para decompor pagina_resumo_semanal (S3776)
# ---------------------------------------------------------------------------
def _renderizar_metricas_semanais(resumo: dict):
    colunas = st.columns(4)
    for col, faixa in zip(colunas, FAIXAS_EXIBIDAS):
        novos = len(resumo["entraram"][faixa])
        delta_texto = f"+{novos} nesta semana" if novos else None
        col.metric(
            f"{ICONES[faixa]} {faixa}",
            resumo["contagens"][faixa],
            delta=delta_texto,
            delta_color="inverse",
            border=True,
        )


def _renderizar_novidades_semana(resumo: dict):
    st.subheader("🔔 Entraram na faixa nos últimos 7 dias")
    houve_novidades = False
    for faixa in FAIXAS_EXIBIDAS:
        t = resumo["entraram"][faixa]
        if t.empty:
            continue
        houve_novidades = True
        titulo = "Venceram" if faixa == FAIXA_VENCIDO else f"Passaram para {faixa}"
        st.markdown(f"**{ICONES[faixa]} {titulo}** ({len(t)})")
        st.dataframe(t, width="stretch", hide_index=True)
    if not houve_novidades:
        st.write("Nenhum contrato mudou de faixa esta semana.")


def _renderizar_expansores_faixas(resumo: dict):
    st.subheader("Contratos em cada faixa")
    for faixa in FAIXAS_EXIBIDAS:
        t = resumo["faixas"][faixa]
        expandir = faixa == FAIXA_ATE_30 and not t.empty
        with st.expander(f"{ICONES[faixa]} {faixa} — {len(t)} contrato(s)", expanded=expandir):
            if t.empty:
                st.write("Nenhum contrato nesta faixa.")
            else:
                st.dataframe(t, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página: Resumo Semanal
# ---------------------------------------------------------------------------
def pagina_resumo_semanal():
    st.title("Resumo Semanal de Contratos")
    resumo = montar_resumo()
    hoje = resumo["hoje"]

    if resumo["total"] == 0:
        st.info("Nenhum contrato no sistema ainda.")
        return

    st.caption(
        f"Posição em {hoje:%d/%m/%Y}. 'Nesta semana' = contratos que passaram para a faixa "
        "nos últimos 7 dias. Gere este resumo sempre no mesmo dia da semana (ex.: segunda-feira) "
        "e cada contrato aparece como novidade uma única vez por faixa."
    )

    _renderizar_metricas_semanais(resumo)

    if not resumo["vencem_semana"].empty:
        st.warning(f"⚠️ {len(resumo['vencem_semana'])} contrato(s) vencem nos próximos 7 dias.")
        st.dataframe(resumo["vencem_semana"], width="stretch", hide_index=True)

    _renderizar_novidades_semana(resumo)
    _renderizar_expansores_faixas(resumo)

    st.subheader("👤 Por fiscal")
    if resumo["por_fiscal"].empty:
        st.write("Nenhum contrato em alerta.")
    else:
        st.dataframe(resumo["por_fiscal"], width="stretch", hide_index=True)

    _renderizar_bloco_downloads(resumo, hoje)
    _renderizar_bloco_agendamento(resumo)