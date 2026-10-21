"""
Painel de Acompanhamento de Projetos e Demandas Técnicas Administrativas.

Rodar com:
    streamlit run app.py

Para expor na rede do setor (outros colegas acessarem pelo navegador):
    streamlit run app.py --server.address 0.0.0.0 --server.port 8501
Depois compartilhe: http://SEU-IP-NA-REDE:8501
"""

import pandas as pd  # type: ignore
import plotly.express as px  # type: ignore
import streamlit as st  # type: ignore

from database import inicializar_banco
from painel import pagina_painel_geral, pagina_resumo_semanal
from queries import (
    atualizar_etapa,
    calcular_kpis,
    carga_por_responsavel,
    excluir_etapa,
    inserir_etapa,
    listar_etapas,
)
from queries_contratos import (
    DIAS_ALERTA_VENCIMENTO,
    ContratoDTO,
    atualizar_contrato,
    buscar_contratos,
    calcular_kpis_contratos,
    excluir_contrato,
    inserir_contrato,
    listar_contratos,
)
from queries_itens import (
    atualizar_item,
    excluir_item,
    inserir_item,
    listar_itens_por_contrato,
    proximo_numero_item,
)
from queries_pedidos import (
    SITUACOES_PEDIDO,
    atualizar_pedido,
    buscar_pedidos,
    calcular_kpis_pedidos,
    excluir_pedido,
    inserir_pedido,
    listar_pedidos,
    normalizar_arp,
)

# Constantes globais para eliminar duplicação de literais (S1192)
PAGINA_ITENS_NOME = "📄 Itens do Contrato"
TIPO_ARP = "Ata de registro de preços"
STATUS_EM_ANDAMENTO = "Em andamento"
ROTULO_RESPONSAVEL = "Responsável"
ROTULO_PERCENTUAL = "% concluído"
ROTULO_OBSERVACOES = "Observações"
ROTULO_SALVAR_ALTERACOES = "Salvar alterações"
ROTULO_ID_PROCESSO = "ID do processo"
ROTULO_SITUACAO = "Situação"
ROTULO_DESCRICAO = "Descrição"
ROTULO_VIGENCIA = "Vigência"
ROTULO_NUMERO_PEDIDO = "Nº do pedido"
ROTULO_DATA_ENVIO = "Data de envio"
FORMATO_DATA_BR = "DD/MM/YYYY"

st.set_page_config(page_title="Painel de TI", layout="wide")
inicializar_banco()

OPCOES_MENU = [
    "📊 Painel Geral",
    "📋 Resumo Semanal",
    "📄 Contratos e Licitações",
    PAGINA_ITENS_NOME,
    "📦 Controle de Pedidos",
    "✏️ Cadastros",
    "📁 Projetos",
]


def ir_para_itens(contrato_id: int):
    """Callback do botão 'Ver itens': roda antes do script reexecutar."""
    st.session_state["contrato_selecionado_id"] = contrato_id
    st.session_state["pagina_radio"] = PAGINA_ITENS_NOME


st.sidebar.title("Painel de TI")
pagina = st.sidebar.radio("Menu", OPCOES_MENU, key="pagina_radio")


def montar_opcoes(df, rotulo):
    """Monta {texto exibido: id} para os seletores sem mostrar o id interno."""
    opcoes = {}
    for row in df.itertuples():
        texto = rotulo(row)
        if texto in opcoes:
            texto = f"{texto} (#{row.id})"
        opcoes[texto] = int(row.id)
    return opcoes


def tipo_curto(tipo: str) -> str:
    return "ARP" if tipo == TIPO_ARP else "Contrato"


def brl(valor) -> str:
    """Formata número como moeda brasileira: R$ 1.550,00"""
    if valor is None or pd.isna(valor):
        return "—"
    texto = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def data_br(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return pd.Timestamp(valor).strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Página: Dashboard
# ---------------------------------------------------------------------------
def pagina_dashboard_projetos():
    st.title("Projetos e Demandas Técnicas")
    df = listar_etapas()

    if df.empty:
        st.info("Nenhuma etapa cadastrada ainda. Use o menu 'Cadastrar / editar etapa'.")
        return

    kpis = calcular_kpis(df)
    col1, col2, col3 = st.columns(3)
    col1.metric("Etapas atrasadas", kpis["atrasadas"])
    col2.metric("Concluídas neste mês", kpis["concluidas_mes"])
    col3.metric(STATUS_EM_ANDAMENTO, kpis["em_andamento"])

    st.subheader("Cronograma (visão Gantt)")
    cor_status = {
        "Concluído": "#5DCAA5",
        STATUS_EM_ANDAMENTO: "#378ADD",
        "Atrasado": "#E24B4A",
    }
    fig = px.timeline(
        df,
        x_start="data_inicio",
        x_end="data_fim",
        y="etapa",
        color="status",
        color_discrete_map=cor_status,
        hover_data=["projeto", "responsavel", "percentual_conclusao"],
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Carga de trabalho por responsável")
        carga = carga_por_responsavel(df)
        if not carga.empty:
            fig_carga = px.bar(carga, x="responsavel", y="etapas_pendentes")
            st.plotly_chart(fig_carga, width="stretch")
        else:
            st.write("Sem etapas pendentes no momento.")

    with col_b:
        st.subheader("Todas as etapas")
        tabela = df[
            ["projeto", "etapa", "responsavel", "data_fim", "percentual_conclusao", "status"]
        ].rename(
            columns={
                "projeto": "Projeto",
                "etapa": "Etapa",
                "responsavel": ROTULO_RESPONSAVEL,
                "data_fim": "Prazo",
                "percentual_conclusao": ROTULO_PERCENTUAL,
                "status": "Status",
            }
        )
        st.dataframe(tabela, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página: Cadastrar / editar etapa
# ---------------------------------------------------------------------------
def _form_nova_etapa():
    st.subheader("Nova etapa")
    with st.form("form_nova_etapa", clear_on_submit=True):
        c1, c2 = st.columns(2)
        projeto = c1.text_input("Projeto")
        etapa = c2.text_input("Etapa")

        c3, c4 = st.columns(2)
        responsavel = c3.text_input(ROTULO_RESPONSAVEL)
        percentual = c4.slider(ROTULO_PERCENTUAL, 0, 100, 0)

        c5, c6 = st.columns(2)
        data_inicio = c5.date_input("Data de início")
        data_fim = c6.date_input("Prazo (data fim)")

        observacoes = st.text_area(ROTULO_OBSERVACOES, "")

        enviado = st.form_submit_button("Salvar nova etapa")
        if enviado:
            if not projeto or not etapa or not responsavel:
                st.error("Preencha ao menos projeto, etapa e responsável.")
            else:
                inserir_etapa(
                    projeto, etapa, responsavel, data_inicio, data_fim, percentual, observacoes
                )
                st.success("Etapa salva com sucesso.")
                st.rerun()


def _form_editar_etapa(df: pd.DataFrame):
    st.divider()
    st.subheader("Editar ou excluir etapa existente")
    if df.empty:
        st.write("Nenhuma etapa cadastrada ainda.")
        return

    opcoes = montar_opcoes(df, lambda r: f"{r.projeto} — {r.etapa}")
    escolha = st.selectbox("Selecione a etapa", list(opcoes.keys()))
    etapa_id = opcoes[escolha]
    registro = df[df["id"] == etapa_id].iloc[0]

    with st.form("form_editar_etapa"):
        c1, c2 = st.columns(2)
        e_projeto = c1.text_input("Projeto", registro["projeto"])
        e_etapa = c2.text_input("Etapa", registro["etapa"])

        c3, c4 = st.columns(2)
        e_responsavel = c3.text_input(ROTULO_RESPONSAVEL, registro["responsavel"])
        e_percentual = c4.slider(ROTULO_PERCENTUAL, 0, 100, int(registro["percentual_conclusao"]))

        c5, c6 = st.columns(2)
        e_data_inicio = c5.date_input("Data de início", registro["data_inicio"].date())
        e_data_fim = c6.date_input("Prazo (data fim)", registro["data_fim"].date())

        e_observacoes = st.text_area(ROTULO_OBSERVACOES, registro["observacoes"] or "")

        col_salvar, col_excluir = st.columns(2)
        salvar = col_salvar.form_submit_button(ROTULO_SALVAR_ALTERACOES)
        excluir = col_excluir.form_submit_button("Excluir etapa")

        if salvar:
            atualizar_etapa(
                etapa_id, e_projeto, e_etapa, e_responsavel, e_data_inicio,
                e_data_fim, e_percentual, e_observacoes
            )
            st.success("Etapa atualizada.")
            st.rerun()

        if excluir:
            excluir_etapa(etapa_id)
            st.warning("Etapa excluída.")
            st.rerun()


def cadastro_etapa():
    df = listar_etapas()
    _form_nova_etapa()
    _form_editar_etapa(df)


# ---------------------------------------------------------------------------
# Página: Contratos e Licitações (dashboard + busca)
# ---------------------------------------------------------------------------
def pagina_contratos():
    st.title("Contratos e Atas de Registro de Preços — TI")
    mostrar_arquivados = st.checkbox(
        "Mostrar também contratos arquivados (que saíram da planilha)", value=False
    )
    df = listar_contratos(incluir_arquivados=mostrar_arquivados)
    if not df.empty:
        df.loc[df["arquivado"] == 1, "status"] = "Arquivado"

    if df.empty:
        st.info(
            "Nenhum contrato cadastrado ainda. Rode 'python import_contratos.py "
            "sua_planilha.xlsx' no terminal, ou cadastre manualmente pelo menu ao lado."
        )
        return

    kpis = calcular_kpis_contratos(df)
    col1, col2, col3 = st.columns(3)
    col1.metric("Vigentes", kpis["vigentes"])
    col2.metric(f"Vencendo em até {DIAS_ALERTA_VENCIMENTO} dias", kpis["vencendo"])
    col3.metric("Vencidos", kpis["vencidos"])

    st.subheader("Buscar contratos")
    texto_busca = st.text_input(
        "Pesquisar por fornecedor, nº do contrato, objeto ou fiscal", ""
    )

    opcoes_status = ["Vigente", "Vencendo em breve", "Vencido", "Sem data definida"]
    if mostrar_arquivados:
        opcoes_status.append("Arquivado")
    status_selecionados = st.multiselect(
        "Filtrar por status", opcoes_status, default=opcoes_status
    )

    resultado = buscar_contratos(df, texto_busca)
    resultado = resultado[resultado["status"].isin(status_selecionados)]

    emoji_status = {
        "Vigente": "🟢",
        "Vencendo em breve": "🟡",
        "Vencido": "🔴",
        "Sem data definida": "⚪",
        "Arquivado": "📦",
    }
    resultado = resultado.copy()
    resultado["dias_para_vencer"] = resultado["dias_para_vencer"].astype("Int64")
    resultado["Status"] = resultado["status"].map(emoji_status) + " " + resultado["status"]

    tabela = resultado[
        [
            "id_processo",
            "tipo",
            "numero_contrato",
            "razao_social",
            "objeto",
            "data_fim",
            "dias_para_vencer",
            "fiscal",
            "Status",
        ]
    ].rename(
        columns={
            "id_processo": ROTULO_ID_PROCESSO,
            "tipo": "Tipo",
            "numero_contrato": "Nº contrato",
            "razao_social": "Fornecedor",
            "objeto": "Objeto",
            "data_fim": "Vencimento",
            "dias_para_vencer": "Dias p/ vencer",
            "fiscal": "Fiscal",
        }
    )
    st.caption(f"{len(tabela)} de {len(df)} contratos exibidos")
    st.dataframe(tabela, width="stretch", hide_index=True)

    st.divider()
    st.subheader("Ver itens de um contrato")
    opcoes_itens = montar_opcoes(
        resultado, lambda r: f"{tipo_curto(r.tipo)} {r.numero_contrato} — {r.razao_social}"
    )
    if opcoes_itens:
        escolha_itens = st.selectbox(
            "Selecione o contrato para ver ou cadastrar os itens", list(opcoes_itens.keys())
        )
        st.button(
            "Ver itens deste contrato →",
            on_click=ir_para_itens,
            args=(int(opcoes_itens[escolha_itens]),),
        )


# ---------------------------------------------------------------------------
# Página: Cadastrar / editar contrato (Dividida para reduzir S3776)
# ---------------------------------------------------------------------------
def _form_novo_contrato():
    st.subheader("Novo contrato / ata")
    with st.form("form_novo_contrato", clear_on_submit=True):
        c1, c2 = st.columns(2)
        id_processo = c1.text_input(ROTULO_ID_PROCESSO)
        tipo = c2.selectbox("Tipo", ["Contrato", TIPO_ARP])

        c3, c4 = st.columns(2)
        numero_contrato = c3.text_input("Nº do contrato")
        cnpj = c4.text_input("CNPJ do fornecedor")

        nome_contrato = st.text_input("Nome do contrato (descrição completa)")

        c5, c6 = st.columns(2)
        razao_social = c5.text_input("Razão social")
        nome_fantasia = c6.text_input("Nome fantasia")

        objeto = st.text_area("Objeto")

        c7, c8 = st.columns(2)
        data_inicio = c7.date_input("Vigência (início)", value=None)
        data_fim = c8.date_input("Vencimento", value=None)

        c9, c10 = st.columns(2)
        fiscal = c9.text_input("Fiscal do contrato")
        unidade_area = c10.text_input("Unidade/Área", "GETI - GERÊNCIA DE TECNOLOGIA DA INFORMAÇÃO")

        situacao_planilha = st.text_input(ROTULO_SITUACAO, STATUS_EM_ANDAMENTO)
        observacoes = st.text_area(ROTULO_OBSERVACOES, "")

        enviado = st.form_submit_button("Salvar novo contrato")
        if enviado:
            if not razao_social or not numero_contrato:
                st.error("Preencha ao menos razão social e nº do contrato.")
            else:
                novo = ContratoDTO(
                    id_processo=id_processo,
                    tipo=tipo,
                    numero_contrato=numero_contrato,
                    nome_contrato=nome_contrato,
                    razao_social=razao_social,
                    nome_fantasia=nome_fantasia,
                    cnpj=cnpj,
                    objeto=objeto,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                    fiscal=fiscal,
                    unidade_area=unidade_area,
                    situacao_planilha=situacao_planilha,
                    observacoes=observacoes,
                )
                inserir_contrato(novo)
                st.success("Contrato salvo com sucesso.")
                st.rerun()


def _executar_acao_contrato(contrato_id: int, dados: ContratoDTO, salvar: bool, excluir: bool):
    """Executa a persistência ou exclusão para reduzir a complexidade cognitiva (S3776)."""
    if salvar:
        atualizar_contrato(contrato_id, dados)
        st.success("Contrato atualizado.")
        st.rerun()
    if excluir:
        excluir_contrato(contrato_id)
        st.warning("Contrato excluído.")
        st.rerun()


def _rotulo_contrato_edicao(r) -> str:
    sufixo_arq = " (arquivado)" if r.arquivado else ""
    return f"{tipo_curto(r.tipo)} {r.numero_contrato} — {r.razao_social}{sufixo_arq}"


def _obter_data_ou_none(valor):
    return valor.date() if pd.notna(valor) else None


def _form_editar_contrato(df: pd.DataFrame):
    st.divider()
    st.subheader("Editar ou excluir contrato existente")
    if df.empty:
        st.write("Nenhum contrato cadastrado ainda.")
        return

    opcoes = montar_opcoes(df, _rotulo_contrato_edicao)
    escolha = st.selectbox("Selecione o contrato", list(opcoes.keys()))
    contrato_id = opcoes[escolha]
    registro = df[df["id"] == contrato_id].iloc[0]

    with st.form("form_editar_contrato"):
        c1, c2 = st.columns(2)
        e_id_processo = c1.text_input(ROTULO_ID_PROCESSO, registro["id_processo"] or "")
        idx_tipo = 0 if registro["tipo"] == "Contrato" else 1
        e_tipo = c2.selectbox("Tipo", ["Contrato", TIPO_ARP], index=idx_tipo)

        c3, c4 = st.columns(2)
        e_numero_contrato = c3.text_input("Nº do contrato", registro["numero_contrato"] or "")
        e_cnpj = c4.text_input("CNPJ do fornecedor", registro["cnpj"] or "")

        e_nome_contrato = st.text_input(
            "Nome do contrato (descrição completa)", registro["nome_contrato"] or ""
        )

        c5, c6 = st.columns(2)
        e_razao_social = c5.text_input("Razão social", registro["razao_social"] or "")
        e_nome_fantasia = c6.text_input("Nome fantasia", registro["nome_fantasia"] or "")

        e_objeto = st.text_area("Objeto", registro["objeto"] or "")

        c7, c8 = st.columns(2)
        e_data_inicio = c7.date_input("Vigência (início)", _obter_data_ou_none(registro["data_inicio"]))
        e_data_fim = c8.date_input("Vencimento", _obter_data_ou_none(registro["data_fim"]))

        c9, c10 = st.columns(2)
        e_fiscal = c9.text_input("Fiscal do contrato", registro["fiscal"] or "")
        e_unidade_area = c10.text_input("Unidade/Área", registro["unidade_area"] or "")

        e_situacao_planilha = st.text_input(ROTULO_SITUACAO, registro["situacao_planilha"] or "")
        e_observacoes = st.text_area(ROTULO_OBSERVACOES, registro["observacoes"] or "")
        e_arquivado = st.checkbox(
            "Arquivado (fora do painel e dos resumos, mas com os itens preservados)",
            value=bool(registro["arquivado"]),
        )

        col_salvar, col_excluir = st.columns(2)
        salvar = col_salvar.form_submit_button(ROTULO_SALVAR_ALTERACOES)
        excluir = col_excluir.form_submit_button("Excluir contrato")

        dados_atualizados = ContratoDTO(
            id_processo=e_id_processo,
            tipo=e_tipo,
            numero_contrato=e_numero_contrato,
            nome_contrato=e_nome_contrato,
            razao_social=e_razao_social,
            nome_fantasia=e_nome_fantasia,
            cnpj=e_cnpj,
            objeto=e_objeto,
            data_inicio=e_data_inicio,
            data_fim=e_data_fim,
            fiscal=e_fiscal,
            unidade_area=e_unidade_area,
            situacao_planilha=e_situacao_planilha,
            observacoes=e_observacoes,
            arquivado=e_arquivado,
        )

        _executar_acao_contrato(contrato_id, dados_atualizados, salvar, excluir)


def cadastro_contrato():
    df = listar_contratos(incluir_arquivados=True)
    _form_novo_contrato()
    _form_editar_contrato(df)


# ---------------------------------------------------------------------------
# Página: Itens do Contrato (Dividida para reduzir S3776)
# ---------------------------------------------------------------------------
def _tabela_itens_contrato(itens: pd.DataFrame):
    st.subheader("Itens cadastrados")
    if itens.empty:
        st.write("Nenhum item cadastrado para este contrato ainda.")
        return

    exibicao = pd.DataFrame(
        {
            "Item": itens["item_numero"],
            ROTULO_DESCRICAO: itens["descricao"],
            "Local": itens["local"],
            "Unidade": itens["unidade"],
            "Quantidade": itens["quantidade"],
            "Valor mensal": itens["valor_mensal"].map(brl),
            "Valor total do item": itens["valor_total_item"].map(brl),
            ROTULO_VIGENCIA: itens["vigencia_texto"],
        }
    )
    st.dataframe(exibicao, width="stretch", hide_index=True)

    soma_itens = itens["valor_total_item"].fillna(0).sum()
    m1, m2 = st.columns(2)
    m1.metric("Valor global do contrato (soma dos itens)", brl(soma_itens), border=True)
    m2.metric("Itens cadastrados", len(itens), border=True)


def _form_novo_item(contrato_id: int, itens: pd.DataFrame):
    st.divider()
    st.subheader("Novo item")
    proximo = proximo_numero_item(itens)
    with st.form("form_novo_item", clear_on_submit=True):
        f1, f2 = st.columns([1, 3])
        item_numero = f1.text_input(
            "Item (nº)", value=proximo, key=f"novo_item_{contrato_id}_{proximo}"
        )
        descricao = f2.text_input(ROTULO_DESCRICAO)

        f3, f4, f5 = st.columns(3)
        local = f3.text_input("Local")
        unidade = f4.text_input("Unidade", "Mensal")
        quantidade = f5.number_input("Quantidade", min_value=0.0, step=1.0, format="%.2f")

        f6, f7 = st.columns(2)
        valor_mensal = f6.number_input("Valor mensal (R$)", min_value=0.0, step=0.01, format="%.2f")
        valor_total_item = f7.number_input(
            "Valor total do item (R$)", min_value=0.0, step=0.01, format="%.2f"
        )
        vigencia_texto = st.text_input(ROTULO_VIGENCIA, "12 meses")
        st.caption(
            "Se 'Valor total do item' ficar em 0, ele é calculado como quantidade × valor mensal."
        )

        if st.form_submit_button("Salvar item"):
            if not descricao:
                st.error("Informe ao menos a descrição do item.")
            else:
                if valor_total_item == 0 and valor_mensal > 0 and quantidade > 0:
                    valor_total_item = round(quantidade * valor_mensal, 2)
                inserir_item(
                    contrato_id, item_numero, descricao, local, unidade, quantidade,
                    valor_mensal, valor_total_item, vigencia_texto,
                )
                st.success("Item salvo.")
                st.rerun()


def _form_editar_item(itens: pd.DataFrame):
    if itens.empty:
        return

    st.divider()
    st.subheader("Editar ou excluir item")
    opcoes_item = montar_opcoes(
        itens, lambda r: f"Item {r.item_numero} — {r.descricao}"
    )
    escolha_item = st.selectbox("Selecione o item", list(opcoes_item.keys()))
    item_id = opcoes_item[escolha_item]
    reg = itens[itens["id"] == item_id].iloc[0]

    with st.form("form_editar_item"):
        f1, f2 = st.columns([1, 3])
        e_item_numero = f1.text_input("Item (nº)", reg["item_numero"] or "")
        e_descricao = f2.text_input(ROTULO_DESCRICAO, reg["descricao"] or "")

        f3, f4, f5 = st.columns(3)
        e_local = f3.text_input("Local", reg["local"] or "")
        e_unidade = f4.text_input("Unidade", reg["unidade"] or "")
        e_quantidade = f5.number_input(
            "Quantidade", min_value=0.0, step=1.0, format="%.2f",
            value=float(reg["quantidade"] or 0),
        )

        f6, f7 = st.columns(2)
        e_valor_mensal = f6.number_input(
            "Valor mensal (R$)", min_value=0.0, step=0.01, format="%.2f",
            value=float(reg["valor_mensal"] or 0),
        )
        e_valor_total = f7.number_input(
            "Valor total do item (R$)", min_value=0.0, step=0.01, format="%.2f",
            value=float(reg["valor_total_item"] or 0),
        )
        e_vigencia = st.text_input(ROTULO_VIGENCIA, reg["vigencia_texto"] or "")

        b1, b2 = st.columns(2)
        salvar_item = b1.form_submit_button(ROTULO_SALVAR_ALTERACOES)
        excluir_it = b2.form_submit_button("Excluir item")

        if salvar_item:
            atualizar_item(
                item_id, e_item_numero, e_descricao, e_local, e_unidade, e_quantidade,
                e_valor_mensal, e_valor_total, e_vigencia,
            )
            st.success("Item atualizado.")
            st.rerun()
        if excluir_it:
            excluir_item(item_id)
            st.warning("Item excluído.")
            st.rerun()


def pagina_itens():
    st.title("Itens do contrato")
    df_todos = listar_contratos(incluir_arquivados=True)
    atual = st.session_state.get("contrato_selecionado_id")
    atual_arquivado = bool(
        not df_todos.empty and atual in df_todos.loc[df_todos["arquivado"] == 1, "id"].tolist()
    )
    incluir_arquivados = st.checkbox("Incluir contratos arquivados", value=atual_arquivado)
    df_contratos = df_todos if incluir_arquivados else df_todos[df_todos["arquivado"] == 0]

    if df_contratos.empty:
        st.info("Cadastre ou importe contratos antes de cadastrar itens.")
        return

    opcoes = montar_opcoes(
        df_contratos,
        lambda r: f"{tipo_curto(r.tipo)} {r.numero_contrato} — {r.razao_social}"
        + (" (arquivado)" if r.arquivado else ""),
    )
    ids = list(opcoes.values())
    indice = ids.index(atual) if atual in ids else 0

    escolha = st.selectbox("Contrato", list(opcoes.keys()), index=indice)
    contrato_id = opcoes[escolha]
    st.session_state["contrato_selecionado_id"] = contrato_id
    contrato = df_contratos[df_contratos["id"] == contrato_id].iloc[0]

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Contrato:** {contrato['numero_contrato']}")
    c2.markdown(f"**Fornecedor:** {contrato['razao_social']}")
    c3.markdown(f"**Vencimento:** {data_br(contrato['data_fim'])}")
    st.markdown(f"**Objeto:** {contrato['objeto']}")

    itens = listar_itens_por_contrato(contrato_id)
    _tabela_itens_contrato(itens)
    _form_novo_item(contrato_id, itens)
    _form_editar_item(itens)


# ---------------------------------------------------------------------------
# Página: Controle de Pedidos (visão geral + busca)
# ---------------------------------------------------------------------------
def pagina_pedidos():
    st.title("Controle de Pedidos")
    df = listar_pedidos()

    if df.empty:
        st.info("Nenhum pedido cadastrado ainda. Use 'Cadastrar / editar pedido' no menu.")
        return

    kpis = calcular_kpis_pedidos(df)
    k1, k2, k3 = st.columns(3)
    k1.metric("Atrasados", kpis["atrasados"])
    k2.metric(STATUS_EM_ANDAMENTO, kpis["em_andamento"])
    k3.metric("Entregues", kpis["entregues"])

    texto = st.text_input("Pesquisar por ARP, fornecedor, SIC ou nº do pedido", "")
    todos_status = ["Atrasado"] + SITUACOES_PEDIDO
    filtro = st.multiselect("Filtrar por situação", todos_status, default=todos_status)

    rotulos_arp = sorted(
        {normalizar_arp(a): a for a in df["arp"].fillna("") if a}.values()
    )
    escolha_arp = st.selectbox("Filtrar por ARP", ["Todas"] + rotulos_arp)

    resultado = buscar_pedidos(df, texto)
    resultado = resultado[resultado["status_calculado"].isin(filtro)].copy()
    if escolha_arp != "Todas":
        resultado = resultado[
            resultado["arp"].map(normalizar_arp) == normalizar_arp(escolha_arp)
        ]

    emoji = {
        "Atrasado": "🔴",
        "Aguardando envio": "⚪",
        "Enviado": "🟡",
        "Em entrega": "🔵",
        "Entregue": "🟢",
        "Cancelado": "⚫",
    }
    resultado[ROTULO_SITUACAO] = resultado["status_calculado"].map(emoji).fillna("") + " " + resultado[
        "status_calculado"
    ]

    tabela = pd.DataFrame(
        {
            "ARP": resultado["arp"],
            "Fornecedor": resultado["fornecedor"],
            "SIC": resultado["sic"],
            ROTULO_NUMERO_PEDIDO: resultado["numero_pedido"],
            ROTULO_DATA_ENVIO: resultado["data_envio"].map(data_br),
            "Prazo": resultado["prazo"].map(data_br),
            "Restante (dias)": resultado["dias_restantes"],
            ROTULO_SITUACAO: resultado[ROTULO_SITUACAO],
        }
    )
    st.caption(f"{len(tabela)} de {len(df)} pedidos exibidos")
    st.dataframe(tabela, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# Página: Cadastrar / editar pedido (Dividida para reduzir S3776)
# ---------------------------------------------------------------------------
def _obter_dados_arp_padrao(arps: pd.DataFrame):
    outra_arp = "— Outra ARP (digitar) —"
    opcoes_arp = montar_opcoes(arps, lambda r: f"ARP {r.numero_contrato} — {r.razao_social}")
    escolha_arp = st.selectbox("ARP do pedido", list(opcoes_arp.keys()) + [outra_arp])
    if escolha_arp == outra_arp:
        return "", "", "outra"
    ref = arps[arps["id"] == opcoes_arp[escolha_arp]].iloc[0]
    return ref["numero_contrato"], ref["razao_social"], str(ref["id"])


def _form_novo_pedido(arps: pd.DataFrame):
    st.subheader("Novo pedido")
    arp_padrao, fornecedor_padrao, chave_arp = _obter_dados_arp_padrao(arps)

    with st.form("form_novo_pedido", clear_on_submit=True):
        p1, p2 = st.columns(2)
        arp = p1.text_input("Nº da ARP", value=arp_padrao, key=f"ped_arp_{chave_arp}")
        fornecedor = p2.text_input("Fornecedor", value=fornecedor_padrao, key=f"ped_forn_{chave_arp}")

        p3, p4 = st.columns(2)
        sic = p3.text_input("SIC")
        numero_pedido = p4.text_input(ROTULO_NUMERO_PEDIDO)

        p5, p6, p7 = st.columns(3)
        data_envio = p5.date_input(ROTULO_DATA_ENVIO, value=None, format=FORMATO_DATA_BR)
        prazo = p6.date_input("Prazo", value=None, format=FORMATO_DATA_BR)
        situacao = p7.selectbox(ROTULO_SITUACAO, SITUACOES_PEDIDO, index=1)
        st.caption("O 'Restante' (dias até o prazo) é calculado automaticamente.")

        if st.form_submit_button("Salvar pedido"):
            if not fornecedor or not numero_pedido:
                st.error("Preencha ao menos fornecedor e nº do pedido.")
            else:
                inserir_pedido(arp, fornecedor, sic, numero_pedido, data_envio, prazo, situacao)
                st.success("Pedido salvo.")
                st.rerun()


def _form_editar_pedido(df: pd.DataFrame):
    st.divider()
    st.subheader("Editar ou excluir pedido existente")
    if df.empty:
        st.write("Nenhum pedido cadastrado ainda.")
        return

    opcoes = montar_opcoes(df, lambda r: f"{r.numero_pedido} — {r.fornecedor}")
    escolha = st.selectbox("Selecione o pedido", list(opcoes.keys()))
    pedido_id = opcoes[escolha]
    reg = df[df["id"] == pedido_id].iloc[0]

    with st.form("form_editar_pedido"):
        p1, p2 = st.columns(2)
        e_arp = p1.text_input("ARP", reg["arp"] or "")
        e_fornecedor = p2.text_input("Fornecedor", reg["fornecedor"] or "")

        p3, p4 = st.columns(2)
        e_sic = p3.text_input("SIC", reg["sic"] or "")
        e_numero = p4.text_input(ROTULO_NUMERO_PEDIDO, reg["numero_pedido"] or "")

        p5, p6, p7 = st.columns(3)
        e_data_envio = p5.date_input(
            ROTULO_DATA_ENVIO,
            reg["data_envio"].date() if pd.notna(reg["data_envio"]) else None,
            format=FORMATO_DATA_BR,
        )
        e_prazo = p6.date_input(
            "Prazo",
            reg["prazo"].date() if pd.notna(reg["prazo"]) else None,
            format=FORMATO_DATA_BR,
        )
        idx = SITUACOES_PEDIDO.index(reg["situacao"]) if reg["situacao"] in SITUACOES_PEDIDO else 0
        e_situacao = p7.selectbox(ROTULO_SITUACAO, SITUACOES_PEDIDO, index=idx)

        b1, b2 = st.columns(2)
        salvar = b1.form_submit_button(ROTULO_SALVAR_ALTERACOES)
        excluir = b2.form_submit_button("Excluir pedido")

        if salvar:
            atualizar_pedido(
                pedido_id, e_arp, e_fornecedor, e_sic, e_numero, e_data_envio, e_prazo, e_situacao
            )
            st.success("Pedido atualizado.")
            st.rerun()
        if excluir:
            excluir_pedido(pedido_id)
            st.warning("Pedido excluído.")
            st.rerun()


def cadastro_pedido():
    df = listar_pedidos()
    todos_contratos = listar_contratos()
    arps = todos_contratos[todos_contratos["tipo"] == TIPO_ARP]
    _form_novo_pedido(arps)
    _form_editar_pedido(df)


# ---------------------------------------------------------------------------
# Página: Cadastros (três cadastros reunidos em abas)
# ---------------------------------------------------------------------------
def pagina_cadastros():
    st.title("Cadastros")
    aba_contrato, aba_pedido, aba_etapa = st.tabs(
        ["📄 Contratos e ARPs", "📦 Pedidos", "📁 Etapas de projeto"]
    )
    with aba_contrato:
        cadastro_contrato()
    with aba_pedido:
        cadastro_pedido()
    with aba_etapa:
        cadastro_etapa()


# ---------------------------------------------------------------------------
# Despacho: decide qual página desenhar conforme o menu lateral
# ---------------------------------------------------------------------------
if pagina == "📊 Painel Geral":
    pagina_painel_geral()
elif pagina == "📋 Resumo Semanal":
    pagina_resumo_semanal()
elif pagina == "📄 Contratos e Licitações":
    pagina_contratos()
elif pagina == PAGINA_ITENS_NOME:
    pagina_itens()
elif pagina == "📦 Controle de Pedidos":
    pagina_pedidos()
elif pagina == "✏️ Cadastros":
    pagina_cadastros()
elif pagina == "📁 Projetos":
    pagina_dashboard_projetos()