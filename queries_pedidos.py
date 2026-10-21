"""
Funções de acesso a dados (CRUD) para o controle de pedidos feitos a
partir de ARPs (Atas de Registro de Preços).

"Restante" é calculado automaticamente: dias entre hoje e o prazo.
"""

import re
from datetime import date

import pandas as pd # type: ignore

from database import get_connection

SITUACOES_PEDIDO = [
    "Aguardando envio",
    "Enviado",
    "Em entrega",
    "Entregue",
    "Cancelado",
]

SITUACOES_FINAIS = {"Entregue", "Cancelado"}


def listar_pedidos() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM pedidos ORDER BY prazo", conn)
    conn.close()

    if df.empty:
        return df

    df["data_envio"] = pd.to_datetime(df["data_envio"])
    df["prazo"] = pd.to_datetime(df["prazo"])

    hoje = pd.Timestamp(date.today())
    final = df["situacao"].isin(SITUACOES_FINAIS)

    # Restante = dias até o prazo (negativo = já passou). Vazio se o pedido foi
    # entregue/cancelado ou se não há prazo definido.
    df["dias_restantes"] = (df["prazo"] - hoje).dt.days.astype("Float64")
    df.loc[final, "dias_restantes"] = pd.NA

    def calcular_status(row):
        if row["situacao"] in SITUACOES_FINAIS:
            return row["situacao"]
        if pd.notna(row["dias_restantes"]) and row["dias_restantes"] < 0:
            return "Atrasado"
        return row["situacao"]

    df["status_calculado"] = df.apply(calcular_status, axis=1)
    return df


def buscar_pedidos(df: pd.DataFrame, texto: str) -> pd.DataFrame:
    if not texto:
        return df
    texto = texto.lower()
    mascara = pd.Series(False, index=df.index)
    for col in ["arp", "fornecedor", "sic", "numero_pedido"]:
        mascara = mascara | df[col].fillna("").str.lower().str.contains(texto, regex=False)
    return df[mascara]


def inserir_pedido(arp, fornecedor, sic, numero_pedido, data_envio, prazo, situacao):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO pedidos (arp, fornecedor, sic, numero_pedido, data_envio, prazo, situacao)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            arp, fornecedor, sic, numero_pedido,
            data_envio.isoformat() if data_envio else None,
            prazo.isoformat() if prazo else None,
            situacao,
        ),
    )
    conn.commit()
    conn.close()


def atualizar_pedido(pedido_id, arp, fornecedor, sic, numero_pedido, data_envio, prazo, situacao):
    conn = get_connection()
    conn.execute(
        """
        UPDATE pedidos
        SET arp = ?, fornecedor = ?, sic = ?, numero_pedido = ?, data_envio = ?,
            prazo = ?, situacao = ?
        WHERE id = ?
        """,
        (
            arp, fornecedor, sic, numero_pedido,
            data_envio.isoformat() if data_envio else None,
            prazo.isoformat() if prazo else None,
            situacao,
            int(pedido_id),
        ),
    )
    conn.commit()
    conn.close()


def excluir_pedido(pedido_id):
    conn = get_connection()
    conn.execute("DELETE FROM pedidos WHERE id = ?", (int(pedido_id),))
    conn.commit()
    conn.close()


def calcular_kpis_pedidos(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"atrasados": 0, "em_andamento": 0, "entregues": 0}
    status = df["status_calculado"]
    return {
        "atrasados": int((status == "Atrasado").sum()),
        "em_andamento": int((~status.isin(["Atrasado", "Entregue", "Cancelado"])).sum()),
        "entregues": int((status == "Entregue").sum()),
    }


# ---------------------------------------------------------------------------
# Pedidos agrupados por ARP
# ---------------------------------------------------------------------------
def normalizar_arp(texto) -> str:
    """Chave para casar o ARP digitado no pedido com o nº do contrato da ARP.

    '004/2025', '004-2025' e '4/2025' viram todos '4-2025'.
    """
    partes = re.findall(r"\d+", str(texto or ""))
    if partes:
        return "-".join(str(int(p)) for p in partes)
    return re.sub(r"[^0-9a-z]", "", str(texto or "").lower())


def _linha_arp(arp, fornecedor, vencimento, arquivada, chave, sub, cadastrada):
    abertos = sub[~sub["status_calculado"].isin(SITUACOES_FINAIS)] if not sub.empty else sub
    return {
        "arp": arp,
        "fornecedor": fornecedor,
        "vencimento_arp": vencimento,
        "arquivada": int(arquivada),
        "cadastrada": cadastrada,
        "chave": chave,
        "pedidos": len(sub),
        "abertos": len(abertos),
        "atrasados": int((sub["status_calculado"] == "Atrasado").sum()) if not sub.empty else 0,
        "entregues": int((sub["status_calculado"] == "Entregue").sum()) if not sub.empty else 0,
        "proximo_prazo": abertos["prazo"].min() if not abertos.empty else pd.NaT,
    }


def resumo_por_arp(pedidos: pd.DataFrame, arps: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por ARP: as cadastradas (mesmo sem pedidos) e as citadas em pedidos
    mas não cadastradas. `arps` = contratos do tipo ARP."""
    linhas = []
    pedidos = pedidos.copy()
    if not pedidos.empty:
        pedidos["chave"] = pedidos["arp"].map(normalizar_arp)

    chaves_cadastradas = set()
    for r in arps.itertuples():
        chave = normalizar_arp(r.numero_contrato)
        chaves_cadastradas.add(chave)
        sub = pedidos[pedidos["chave"] == chave] if not pedidos.empty else pedidos
        linhas.append(_linha_arp(r.numero_contrato, r.razao_social, r.data_fim, r.arquivado, chave, sub, True))

    if not pedidos.empty:
        for chave, sub in pedidos[~pedidos["chave"].isin(chaves_cadastradas)].groupby("chave"):
            rotulo = sub["arp"].iloc[0] or "(sem ARP informada)"
            linhas.append(_linha_arp(rotulo, sub["fornecedor"].iloc[0], pd.NaT, 0, chave, sub, False))

    return pd.DataFrame(linhas)