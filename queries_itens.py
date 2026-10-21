"""
Funções de acesso a dados (CRUD) para os itens de cada contrato.

Cada linha é um item específico de um contrato (ex: "Link de Internet
Dedicado de 200 Mbps"), cadastrado manualmente a partir do documento.
"""

import pandas as pd # type: ignore

from database import get_connection


def listar_itens_por_contrato(contrato_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM itens_contrato WHERE contrato_id = ? ORDER BY id",
        conn,
        params=(int(contrato_id),),
    )
    conn.close()
    if not df.empty:
        # ordena pelo número do item (1, 2, ..., 10) e não como texto ("1", "10", "2")
        df["_ordem"] = pd.to_numeric(df["item_numero"], errors="coerce")
        df = df.sort_values(["_ordem", "id"]).drop(columns="_ordem").reset_index(drop=True)
    return df


def proximo_numero_item(itens: pd.DataFrame) -> str:
    """Sugere o próximo nº de item: maior número já cadastrado + 1 (começa em 1)."""
    if itens.empty:
        return "1"
    numeros = pd.to_numeric(itens["item_numero"], errors="coerce").dropna()
    if numeros.empty:
        return str(len(itens) + 1)
    return str(int(numeros.max()) + 1)


def inserir_item(
    contrato_id, item_numero, descricao, local, unidade, quantidade,
    valor_mensal, valor_total_item, vigencia_texto,
):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO itens_contrato
            (contrato_id, item_numero, descricao, local, unidade, quantidade,
             valor_mensal, valor_total_item, vigencia_texto)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(contrato_id), item_numero, descricao, local, unidade, quantidade,
            valor_mensal, valor_total_item, vigencia_texto,
        ),
    )
    conn.commit()
    conn.close()


def atualizar_item(
    item_id, item_numero, descricao, local, unidade, quantidade,
    valor_mensal, valor_total_item, vigencia_texto,
):
    conn = get_connection()
    conn.execute(
        """
        UPDATE itens_contrato
        SET item_numero = ?, descricao = ?, local = ?, unidade = ?, quantidade = ?,
            valor_mensal = ?, valor_total_item = ?, vigencia_texto = ?
        WHERE id = ?
        """,
        (
            item_numero, descricao, local, unidade, quantidade,
            valor_mensal, valor_total_item, vigencia_texto,
            int(item_id),
        ),
    )
    conn.commit()
    conn.close()


def excluir_item(item_id):
    conn = get_connection()
    conn.execute("DELETE FROM itens_contrato WHERE id = ?", (int(item_id),))
    conn.commit()
    conn.close()


def contagem_itens_por_contrato() -> pd.DataFrame:
    """Quantidade de itens cadastrados por contrato (para o painel de pendências)."""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT contrato_id, COUNT(*) AS qtd_itens FROM itens_contrato GROUP BY contrato_id",
        conn,
    )
    conn.close()
    return df