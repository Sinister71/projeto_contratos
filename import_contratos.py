"""
Importa a planilha de contratos/ARPs (aba "GETI - Visão geral") para o banco.

Rodar com:
    python import_contratos.py Contratos_e_ARPs.xlsx

Pode (e deve) ser rodado de novo sempre que a planilha for atualizada. Regras:

* A identidade de um contrato é  TIPO + Nº DO CONTRATO  (ex.: "Contrato 115-2025").
  O "ID do processo" NÃO é usado como chave porque muda a cada renovação
  (o 115-2025 foi do processo GDC-0710/2025 para o GDC-0672/2026).
* Contrato que já existe  -> é atualizado (datas, processo, fiscal...). Os itens
  cadastrados e as observações são preservados.
* Contrato novo           -> é inserido.
* Contrato que SAIU da planilha (vencido e retirado, por exemplo) -> é ARQUIVADO,
  não apagado: some do painel, mas os itens continuam guardados. Se voltar para
  a planilha, é reativado automaticamente.
* Contratos cadastrados manualmente na tela "Cadastros" nunca são arquivados
  por este script.
* Se a planilha tiver duas linhas do mesmo contrato (ex.: uma do processo de
  renovação ainda sem datas), vale a linha com a data de vencimento mais recente.
"""

import glob
import os
import sys

import pandas as pd  # type: ignore

from database import PASTA_PROJETO, get_connection, inicializar_banco

COLUNAS_OBRIGATORIAS = [
    "ID do processo",
    "Nome do contrato",
    "CPF/CNPJ",
    "Razão social",
    "Nome fantasia",
    "Nº do contrato",
    "Objeto resumido",
    "Vigência",
    "Vencimento",
    "Fiscal do contrato",
    "Unidade/Área",
    "Situação",
]


def limpar_nome_coluna(nome: str) -> str:
    # A planilha original tem caracteres invisíveis (U+200E) em alguns cabeçalhos
    return str(nome).replace("\u200e", "").strip()


def inferir_tipo(nome_contrato: str) -> str:
    nome_contrato = (nome_contrato or "").strip().lower()
    if nome_contrato.startswith("ata de registro de preços"):
        return "Ata de registro de preços"
    return "Contrato"


def _texto(valor) -> str:
    return "" if pd.isna(valor) else str(valor).strip()


def _data(valor):
    return None if pd.isna(valor) else pd.Timestamp(valor).date().isoformat()


def ler_planilha(caminho_xlsx: str) -> list[dict]:
    df = pd.read_excel(caminho_xlsx, sheet_name=0)
    df.columns = [limpar_nome_coluna(c) for c in df.columns]

    faltando = set(COLUNAS_OBRIGATORIAS) - set(df.columns)
    if faltando:
        raise ValueError(f"Colunas esperadas não encontradas na planilha: {sorted(faltando)}")

    registros = []
    for _, row in df.iterrows():
        nome = _texto(row["Nome do contrato"])
        registros.append(
            {
                "id_processo": _texto(row["ID do processo"]),
                "tipo": inferir_tipo(nome),
                "numero_contrato": _texto(row["Nº do contrato"]),
                "nome_contrato": nome,
                "razao_social": _texto(row["Razão social"]),
                "nome_fantasia": _texto(row["Nome fantasia"]),
                "cnpj": _texto(row["CPF/CNPJ"]),
                "objeto": _texto(row["Objeto resumido"]),
                "data_inicio": _data(row["Vigência"]),
                "data_fim": _data(row["Vencimento"]),
                "fiscal": _texto(row["Fiscal do contrato"]),
                "unidade_area": _texto(row["Unidade/Área"]),
                "situacao_planilha": _texto(row["Situação"]),
            }
        )
    return registros


def colapsar_duplicados(registros: list[dict]) -> tuple[list[dict], int]:
    """Mesmo tipo + nº duas vezes na planilha: fica a linha de vencimento mais recente."""
    melhores: dict[tuple, dict] = {}
    for r in registros:
        chave = (r["tipo"], r["numero_contrato"])
        atual = melhores.get(chave)
        if atual is None or (r["data_fim"] or "") > (atual["data_fim"] or ""):
            melhores[chave] = r
    return list(melhores.values()), len(registros) - len(melhores)


# ---------------------------------------------------------------------------
# Funções de decomposição para reduzir a complexidade cognitiva (S3776 / S1515)
# ---------------------------------------------------------------------------
def _selecionar_melhor_candidato(candidatos: list, r: dict):
    """Prioridade: mesmo processo > itens cadastrados > vencimento > ID mais antigo."""
    def prioridade(c):
        return (
            0 if c[1] == r["id_processo"] else 1,
            0 if c[7] > 0 else 1,
            0 if c[6] else 1,
            c[0],
        )

    return min(candidatos, key=prioridade)


def _atualizar_contrato_existente(cur, r: dict, escolhido: tuple, resumo: dict, usados: set):
    usados.add(escolhido[0])
    if escolhido[1] != r["id_processo"]:
        resumo["renovados"].append((r["tipo"], r["numero_contrato"], escolhido[1], r["id_processo"]))
    if escolhido[4]:
        resumo["reativados"] += 1

    cur.execute(
        """
        UPDATE contratos
        SET id_processo = ?, nome_contrato = ?, razao_social = ?, nome_fantasia = ?,
            cnpj = ?, objeto = ?, data_inicio = ?, data_fim = ?, fiscal = ?,
            unidade_area = ?, situacao_planilha = ?, arquivado = 0, origem = 'planilha'
        WHERE id = ?
        """,
        (
            r["id_processo"], r["nome_contrato"], r["razao_social"], r["nome_fantasia"],
            r["cnpj"], r["objeto"], r["data_inicio"], r["data_fim"], r["fiscal"],
            r["unidade_area"], r["situacao_planilha"], escolhido[0],
        ),
    )
    resumo["atualizados"] += 1


def _inserir_novo_contrato(cur, r: dict, resumo: dict, usados: set):
    cur.execute(
        """
        INSERT INTO contratos
            (id_processo, tipo, numero_contrato, nome_contrato, razao_social, nome_fantasia,
             cnpj, objeto, data_inicio, data_fim, fiscal, unidade_area, situacao_planilha,
             observacoes, arquivado, origem)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 0, 'planilha')
        """,
        (
            r["id_processo"], r["tipo"], r["numero_contrato"], r["nome_contrato"],
            r["razao_social"], r["nome_fantasia"], r["cnpj"], r["objeto"],
            r["data_inicio"], r["data_fim"], r["fiscal"], r["unidade_area"],
            r["situacao_planilha"],
        ),
    )
    usados.add(cur.lastrowid)
    resumo["novos"] += 1


def _arquivar_ausentes(cur, chaves_planilha: set, usados: set, resumo: dict):
    cur.execute(
        """
        SELECT c.id, c.tipo, c.numero_contrato, c.razao_social,
               (SELECT COUNT(*) FROM itens_contrato i WHERE i.contrato_id = c.id)
        FROM contratos c
        WHERE c.arquivado = 0 AND c.origem = 'planilha'
        """
    )
    for cid, tipo, numero, razao, qtd_itens in cur.fetchall():
        if cid not in usados:
            cur.execute("UPDATE contratos SET arquivado = 1 WHERE id = ?", (cid,))
            if (tipo, (numero or "").strip()) in chaves_planilha:
                resumo["substituidos"].append((tipo, numero, razao, qtd_itens))
            else:
                resumo["arquivados"].append((tipo, numero, razao, qtd_itens))


def importar(caminho_xlsx: str) -> dict:
    inicializar_banco()

    registros, colapsados = colapsar_duplicados(ler_planilha(caminho_xlsx))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT c.id, c.id_processo, c.tipo, c.numero_contrato, c.arquivado, c.origem, c.data_fim,
               (SELECT COUNT(*) FROM itens_contrato i WHERE i.contrato_id = c.id)
        FROM contratos c ORDER BY c.id
        """
    )
    existentes = cur.fetchall()
    por_chave: dict[tuple, list] = {}
    for linha in existentes:
        por_chave.setdefault((linha[2], (linha[3] or "").strip()), []).append(linha)

    usados: set[int] = set()
    resumo = {
        "novos": 0,
        "atualizados": 0,
        "renovados": [],
        "reativados": 0,
        "arquivados": [],
        "substituidos": [],
        "colapsados": colapsados,
    }

    for r in registros:
        candidatos = [c for c in por_chave.get((r["tipo"], r["numero_contrato"]), []) if c[0] not in usados]
        escolhido = _selecionar_melhor_candidato(candidatos, r) if candidatos else None

        if escolhido:
            _atualizar_contrato_existente(cur, r, escolhido, resumo, usados)
        else:
            _inserir_novo_contrato(cur, r, resumo, usados)

    chaves_planilha = {(r["tipo"], r["numero_contrato"]) for r in registros}
    _arquivar_ausentes(cur, chaves_planilha, usados, resumo)

    conn.commit()
    conn.close()
    return resumo


def imprimir_resumo(resumo: dict):
    print(
        f"{resumo['novos']} novos | {resumo['atualizados']} atualizados "
        f"({len(resumo['renovados'])} com novo ID de processo = renovações) | "
        f"{resumo['reativados']} reativados | {len(resumo['arquivados'])} arquivados "
        f"(saíram da planilha) | {len(resumo['substituidos'])} registros antigos substituídos"
    )
    if resumo["colapsados"]:
        print(f"  {resumo['colapsados']} linha(s) repetida(s) na planilha foram unificadas (vale a de vencimento mais recente).")
    for tipo, numero, antigo, novo in resumo["renovados"]:
        print(f"  Renovado: {tipo} {numero}  ({antigo} -> {novo})")
    for tipo, numero, razao, qtd_itens in resumo["substituidos"]:
        extra = f"  [{qtd_itens} iten(s)]" if qtd_itens else ""
        print(f"  Registro antigo substituído (o contrato segue na planilha): {tipo} {numero} - {razao}{extra}")
    for tipo, numero, razao, qtd_itens in resumo["arquivados"]:
        extra = f"  [{qtd_itens} iten(s) preservado(s)]" if qtd_itens else ""
        print(f"  Arquivado (saiu da planilha): {tipo} {numero} - {razao}{extra}")


def _localizar_arquivo(caminho: str) -> str | None:
    candidatos = [caminho, os.path.join(PASTA_PROJETO, caminho)]
    return next((c for c in candidatos if os.path.isfile(c)), None)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python import_contratos.py caminho/para/planilha.xlsx")
        sys.exit(1)

    arquivo = _localizar_arquivo(sys.argv[1])
    if not arquivo:
        print(f"Arquivo não encontrado: {sys.argv[1]}")
        encontrados = glob.glob("*.xlsx") + glob.glob(os.path.join(PASTA_PROJETO, "*.xlsx"))
        if encontrados:
            print("Planilhas .xlsx encontradas nesta pasta:")
            for e in sorted(set(encontrados)):
                print(f"  - {os.path.basename(e)}")
        else:
            print("Nenhuma planilha .xlsx na pasta atual. Copie o arquivo para cá ou informe o caminho completo.")
        sys.exit(1)

    imprimir_resumo(importar(arquivo))